"""
Unit tests for IP address hashing utilities.

Tests the hash_ip_address function to ensure consistent hashing behavior
for both IPv4 and IPv6 addresses, proper error handling, and hash stability.

Requirements: 10.20
"""

import pytest
from voting.utils import hash_ip_address, hash_ip_address_safe


class TestHashIPAddress:
    """Test suite for hash_ip_address function."""

    def test_hash_ipv4_address(self):
        """Test hashing of IPv4 addresses."""
        ip = "192.168.1.1"
        hashed = hash_ip_address(ip)
        
        # Verify hash is a 64-character hexadecimal string
        assert len(hashed) == 64
        assert all(c in '0123456789abcdef' for c in hashed)
        
    def test_hash_ipv6_address(self):
        """Test hashing of IPv6 addresses."""
        ip = "2001:0db8:85a3:0000:0000:8a2e:0370:7334"
        hashed = hash_ip_address(ip)
        
        # Verify hash is a 64-character hexadecimal string
        assert len(hashed) == 64
        assert all(c in '0123456789abcdef' for c in hashed)
        
    def test_hash_ipv6_compressed(self):
        """Test hashing of compressed IPv6 addresses."""
        ip = "2001:db8::1"
        hashed = hash_ip_address(ip)
        
        # Verify hash is valid
        assert len(hashed) == 64
        assert all(c in '0123456789abcdef' for c in hashed)
        
    def test_hash_consistency_ipv4(self):
        """Test that the same IPv4 address always produces the same hash."""
        ip = "192.168.1.100"
        hash1 = hash_ip_address(ip)
        hash2 = hash_ip_address(ip)
        hash3 = hash_ip_address(ip)
        
        assert hash1 == hash2 == hash3
        
    def test_hash_consistency_ipv6(self):
        """Test that the same IPv6 address always produces the same hash."""
        ip = "2001:db8:85a3::8a2e:370:7334"
        hash1 = hash_ip_address(ip)
        hash2 = hash_ip_address(ip)
        hash3 = hash_ip_address(ip)
        
        assert hash1 == hash2 == hash3
        
    def test_ipv6_normalization(self):
        """Test that different representations of the same IPv6 address produce the same hash."""
        # These are all the same IPv6 address in different formats
        ip1 = "2001:0db8:0000:0000:0000:0000:0000:0001"
        ip2 = "2001:db8::1"
        ip3 = "2001:db8:0:0:0:0:0:1"
        
        hash1 = hash_ip_address(ip1)
        hash2 = hash_ip_address(ip2)
        hash3 = hash_ip_address(ip3)
        
        assert hash1 == hash2 == hash3
        
    def test_different_addresses_produce_different_hashes(self):
        """Test that different IP addresses produce different hashes."""
        ip1 = "192.168.1.1"
        ip2 = "192.168.1.2"
        ip3 = "10.0.0.1"
        
        hash1 = hash_ip_address(ip1)
        hash2 = hash_ip_address(ip2)
        hash3 = hash_ip_address(ip3)
        
        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3
        
    def test_localhost_ipv4(self):
        """Test hashing of localhost IPv4 address."""
        ip = "127.0.0.1"
        hashed = hash_ip_address(ip)
        
        assert len(hashed) == 64
        assert all(c in '0123456789abcdef' for c in hashed)
        
    def test_localhost_ipv6(self):
        """Test hashing of localhost IPv6 address."""
        ip = "::1"
        hashed = hash_ip_address(ip)
        
        assert len(hashed) == 64
        assert all(c in '0123456789abcdef' for c in hashed)
        
    def test_empty_string_raises_error(self):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError, match="IP address cannot be empty"):
            hash_ip_address("")
            
    def test_invalid_ipv4_format_raises_error(self):
        """Test that invalid IPv4 format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid IP address format"):
            hash_ip_address("256.256.256.256")
            
    def test_invalid_ipv6_format_raises_error(self):
        """Test that invalid IPv6 format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid IP address format"):
            hash_ip_address("gggg::1")
            
    def test_random_string_raises_error(self):
        """Test that random string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid IP address format"):
            hash_ip_address("not-an-ip-address")
            
    def test_hash_is_sha256(self):
        """Test that the hash is indeed SHA-256 (64 hex characters)."""
        ip = "8.8.8.8"
        hashed = hash_ip_address(ip)
        
        # SHA-256 produces 32 bytes = 64 hexadecimal characters
        assert len(hashed) == 64
        
    def test_known_hash_values(self):
        """Test against known SHA-256 hash values for verification."""
        import hashlib
        
        # Test case 1: Simple IPv4
        ip1 = "192.168.1.1"
        expected_hash1 = hashlib.sha256(ip1.encode('utf-8')).hexdigest()
        assert hash_ip_address(ip1) == expected_hash1
        
        # Test case 2: IPv6 (compressed form)
        ip2 = "2001:db8::1"
        expected_hash2 = hashlib.sha256(ip2.encode('utf-8')).hexdigest()
        assert hash_ip_address(ip2) == expected_hash2
        
    def test_edge_case_ipv4_addresses(self):
        """Test edge case IPv4 addresses."""
        # All zeros
        assert len(hash_ip_address("0.0.0.0")) == 64
        
        # All 255s
        assert len(hash_ip_address("255.255.255.255")) == 64
        
        # Private network ranges
        assert len(hash_ip_address("10.0.0.0")) == 64
        assert len(hash_ip_address("172.16.0.0")) == 64
        assert len(hash_ip_address("192.168.0.0")) == 64


class TestHashIPAddressSafe:
    """Test suite for hash_ip_address_safe function."""
    
    def test_hash_valid_ip_returns_same_as_regular_function(self):
        """Test that valid IP addresses produce the same hash as the regular function."""
        ip = "192.168.1.1"
        assert hash_ip_address_safe(ip) == hash_ip_address(ip)
        
    def test_none_returns_default_hash(self):
        """Test that None returns the default hash for 0.0.0.0."""
        default_hash = hash_ip_address("0.0.0.0")
        assert hash_ip_address_safe(None) == default_hash
        
    def test_empty_string_returns_default_hash(self):
        """Test that empty string returns the default hash for 0.0.0.0."""
        default_hash = hash_ip_address("0.0.0.0")
        assert hash_ip_address_safe("") == default_hash
        
    def test_invalid_ip_returns_default_hash(self):
        """Test that invalid IP address returns the default hash for 0.0.0.0."""
        default_hash = hash_ip_address("0.0.0.0")
        assert hash_ip_address_safe("not-an-ip") == default_hash
        assert hash_ip_address_safe("999.999.999.999") == default_hash
        assert hash_ip_address_safe("invalid::ip::v6") == default_hash
        
    def test_consistency_of_default_hash(self):
        """Test that all invalid/missing values return the same default hash."""
        hash1 = hash_ip_address_safe(None)
        hash2 = hash_ip_address_safe("")
        hash3 = hash_ip_address_safe("invalid")
        
        assert hash1 == hash2 == hash3


class TestIPHashingIntegration:
    """Integration tests for IP hashing in the context of voting models."""
    
    def test_hash_format_matches_model_field_length(self):
        """Test that hash length matches the model field max_length (64)."""
        from voting.models import Vote, VoteAttempt, AuditLog
        
        # Get the max_length from model fields
        vote_ip_hash_field = Vote._meta.get_field('ip_hash')
        attempt_ip_hash_field = VoteAttempt._meta.get_field('ip_hash')
        audit_ip_hash_field = AuditLog._meta.get_field('ip_hash')
        
        assert vote_ip_hash_field.max_length == 64
        assert attempt_ip_hash_field.max_length == 64
        assert audit_ip_hash_field.max_length == 64
        
        # Verify our hashes fit within the field length
        test_ip = "192.168.1.1"
        hashed = hash_ip_address(test_ip)
        
        assert len(hashed) <= 64
        assert len(hashed) == 64  # SHA-256 is always 64 hex chars
        
    def test_multiple_ips_produce_unique_hashes(self):
        """Test that a batch of different IPs produce unique hashes."""
        ips = [
            "192.168.1.1",
            "192.168.1.2",
            "10.0.0.1",
            "8.8.8.8",
            "1.1.1.1",
            "2001:db8::1",
            "2001:db8::2",
            "::1",
        ]
        
        hashes = [hash_ip_address(ip) for ip in ips]
        
        # All hashes should be unique
        assert len(hashes) == len(set(hashes))
        
    def test_hash_stability_across_multiple_calls(self):
        """Test that hash remains stable across many calls."""
        ip = "192.168.100.50"
        first_hash = hash_ip_address(ip)
        
        # Call 100 times and verify consistency
        for _ in range(100):
            assert hash_ip_address(ip) == first_hash
