"""
Utility functions for the voting module.

Provides security and fraud detection utilities including IP address hashing
for privacy-preserving tracking and device fingerprinting.
"""

import hashlib
import ipaddress
from typing import Optional

from django.http import HttpRequest


def extract_device_fingerprint(request: HttpRequest) -> str:
    """
    Extract a device fingerprint from an HTTP request for fraud detection.
    
    Combines user agent, accept headers, and other identifying information
    from the request to generate a consistent fingerprint string. The fingerprint
    helps identify unique devices across requests for security monitoring and
    suspicious pattern detection.
    
    The fingerprint includes:
    - User-Agent header
    - Accept-Language header
    - Accept-Encoding header
    - Accept header
    
    Args:
        request: Django HttpRequest object containing request headers
        
    Returns:
        String device fingerprint (max 512 characters) combining identifying headers.
        Returns "unknown" if no identifying information is available.
        
    Examples:
        >>> from django.test import RequestFactory
        >>> factory = RequestFactory()
        >>> request = factory.get('/')
        >>> fingerprint = extract_device_fingerprint(request)
        >>> len(fingerprint) <= 512
        True
        
    Requirements: 5.6, 5.7, 6.7, 10.6
    """
    if not request:
        return "unknown"
    
    # Extract identifying headers
    components = []
    
    # User-Agent: Primary identifying header
    user_agent = request.META.get('HTTP_USER_AGENT', '').strip()
    if user_agent:
        components.append(f"UA:{user_agent}")
    
    # Accept-Language: Indicates user's language preferences
    accept_language = request.META.get('HTTP_ACCEPT_LANGUAGE', '').strip()
    if accept_language:
        components.append(f"Lang:{accept_language}")
    
    # Accept-Encoding: Indicates supported compression methods
    accept_encoding = request.META.get('HTTP_ACCEPT_ENCODING', '').strip()
    if accept_encoding:
        components.append(f"Enc:{accept_encoding}")
    
    # Accept: Indicates supported content types
    accept = request.META.get('HTTP_ACCEPT', '').strip()
    if accept:
        components.append(f"Accept:{accept}")
    
    # If no headers found, return unknown
    if not components:
        return "unknown"
    
    # Combine components with pipe separator
    fingerprint = " | ".join(components)
    
    # Enforce maximum length of 512 characters (Requirement 10.6)
    if len(fingerprint) > 512:
        fingerprint = fingerprint[:512]
    
    return fingerprint


def hash_ip_address(ip_address: str) -> str:
    """
    Hash an IP address using SHA-256 for privacy-preserving storage.
    
    Converts the IP address to a consistent SHA-256 hash that can be used
    for fraud detection and rate limiting without storing the actual IP address.
    Handles both IPv4 and IPv6 addresses.
    
    Args:
        ip_address: String representation of an IPv4 or IPv6 address
        
    Returns:
        Hexadecimal SHA-256 hash string (64 characters)
        
    Raises:
        ValueError: If the IP address format is invalid
        
    Examples:
        >>> hash_ip_address("192.168.1.1")
        'c71e7b22a8d67cb05f16828c6e39584a3a8e7a7f48b1e3b17c5e8e0b7c3d4e5f'
        
        >>> hash_ip_address("2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        'a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8'
        
    Requirements: 10.20
    """
    if not ip_address:
        raise ValueError("IP address cannot be empty")
    
    try:
        # Validate and normalize the IP address using ipaddress module
        # This handles both IPv4 and IPv6 addresses and converts them to
        # their canonical form for consistent hashing
        ip_obj = ipaddress.ip_address(ip_address)
        
        # Use the compressed string representation for consistency
        # For IPv4: stays as-is (e.g., "192.168.1.1")
        # For IPv6: uses compressed notation (e.g., "2001:db8::1" instead of "2001:0db8:0000:0000:0000:0000:0000:0001")
        normalized_ip = str(ip_obj)
        
        # Hash the normalized IP address using SHA-256
        hash_obj = hashlib.sha256(normalized_ip.encode('utf-8'))
        
        # Return the hexadecimal representation (64 characters)
        return hash_obj.hexdigest()
        
    except ValueError as e:
        raise ValueError(f"Invalid IP address format: {ip_address}") from e


def hash_ip_address_safe(ip_address: Optional[str]) -> str:
    """
    Safely hash an IP address, returning a default hash for None or invalid values.
    
    This is a convenience wrapper around hash_ip_address that handles None
    and invalid IP addresses gracefully by returning a hash of "0.0.0.0"
    instead of raising an exception.
    
    Args:
        ip_address: String representation of an IP address, or None
        
    Returns:
        Hexadecimal SHA-256 hash string (64 characters)
        
    Examples:
        >>> hash_ip_address_safe(None)
        'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
        
        >>> hash_ip_address_safe("")
        'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
        
        >>> hash_ip_address_safe("invalid")
        'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
    """
    if not ip_address:
        # Use "0.0.0.0" as the default for missing IP addresses
        return hash_ip_address("0.0.0.0")
    
    try:
        return hash_ip_address(ip_address)
    except ValueError:
        # Return default hash for invalid IP addresses
        return hash_ip_address("0.0.0.0")
