"""
Unit tests for device fingerprinting utilities.

Tests the extract_device_fingerprint function to ensure consistent fingerprint
generation from HTTP headers, proper handling of missing headers, and length
constraints.

Requirements: 5.6, 5.7, 6.7, 10.6
"""

import pytest
from django.test import RequestFactory
from voting.utils import extract_device_fingerprint


class TestExtractDeviceFingerprint:
    """Test suite for extract_device_fingerprint function."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.factory = RequestFactory()
        
    def test_fingerprint_with_all_headers(self):
        """Test fingerprint generation with all identifying headers present."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9',
            HTTP_ACCEPT_ENCODING='gzip, deflate, br',
            HTTP_ACCEPT='text/html,application/xhtml+xml'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        # Should contain all components
        assert 'UA:Mozilla/5.0 (Windows NT 10.0; Win64; x64)' in fingerprint
        assert 'Lang:en-US,en;q=0.9' in fingerprint
        assert 'Enc:gzip, deflate, br' in fingerprint
        assert 'Accept:text/html,application/xhtml+xml' in fingerprint
        
    def test_fingerprint_consistency(self):
        """Test that same headers produce same fingerprint."""
        request1 = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0',
            HTTP_ACCEPT_LANGUAGE='en-US'
        )
        
        request2 = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0',
            HTTP_ACCEPT_LANGUAGE='en-US'
        )
        
        fingerprint1 = extract_device_fingerprint(request1)
        fingerprint2 = extract_device_fingerprint(request2)
        
        assert fingerprint1 == fingerprint2
        
    def test_fingerprint_different_user_agents(self):
        """Test that different user agents produce different fingerprints."""
        request1 = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0)',
        )
        
        request2 = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (Macintosh; Intel Mac OS X)',
        )
        
        fingerprint1 = extract_device_fingerprint(request1)
        fingerprint2 = extract_device_fingerprint(request2)
        
        assert fingerprint1 != fingerprint2
        
    def test_fingerprint_with_only_user_agent(self):
        """Test fingerprint generation with only User-Agent header."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (iPhone; CPU iPhone OS 14_0)'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        assert 'UA:Mozilla/5.0 (iPhone; CPU iPhone OS 14_0)' in fingerprint
        assert 'Lang:' not in fingerprint
        assert 'Enc:' not in fingerprint
        
    def test_fingerprint_with_no_headers(self):
        """Test fingerprint generation when no identifying headers are present."""
        request = self.factory.get('/')
        
        fingerprint = extract_device_fingerprint(request)
        
        # Should return "unknown" when no headers are available
        assert fingerprint == "unknown"
        
    def test_fingerprint_maximum_length_512_chars(self):
        """Test that fingerprint is truncated to 512 characters (Requirement 10.6)."""
        # Create headers that would exceed 512 characters
        long_user_agent = 'A' * 300
        long_accept = 'B' * 300
        
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT=long_user_agent,
            HTTP_ACCEPT=long_accept
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        # Should be truncated to exactly 512 characters
        assert len(fingerprint) == 512
        
    def test_fingerprint_within_512_char_limit(self):
        """Test that normal fingerprints are well within the 512 character limit."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9',
            HTTP_ACCEPT_ENCODING='gzip, deflate, br',
            HTTP_ACCEPT='text/html,application/xhtml+xml,application/xml;q=0.9'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        # Should be well within the limit
        assert len(fingerprint) < 512
        
    def test_fingerprint_handles_empty_header_values(self):
        """Test fingerprint generation when headers are present but empty."""
        # Django's test request factory doesn't typically create empty headers,
        # but we can test the behavior with whitespace
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='   ',  # Only whitespace
            HTTP_ACCEPT_LANGUAGE='en-US'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        # Empty/whitespace-only headers should be ignored after strip()
        assert 'UA:' not in fingerprint or fingerprint == "unknown"
        
    def test_fingerprint_with_accept_language(self):
        """Test fingerprint includes Accept-Language header."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0',
            HTTP_ACCEPT_LANGUAGE='fr-FR,fr;q=0.9,en;q=0.8'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        assert 'Lang:fr-FR,fr;q=0.9,en;q=0.8' in fingerprint
        
    def test_fingerprint_with_accept_encoding(self):
        """Test fingerprint includes Accept-Encoding header."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0',
            HTTP_ACCEPT_ENCODING='gzip, deflate, br, zstd'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        assert 'Enc:gzip, deflate, br, zstd' in fingerprint
        
    def test_fingerprint_with_accept_header(self):
        """Test fingerprint includes Accept header."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0',
            HTTP_ACCEPT='application/json,text/plain,*/*'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        assert 'Accept:application/json,text/plain,*/*' in fingerprint
        
    def test_fingerprint_format_uses_pipe_separator(self):
        """Test that fingerprint components are separated by pipe."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0',
            HTTP_ACCEPT_LANGUAGE='en-US'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        # Should use " | " as separator between components
        assert ' | ' in fingerprint
        
    def test_fingerprint_component_order(self):
        """Test that fingerprint components appear in consistent order."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='TestUA',
            HTTP_ACCEPT_LANGUAGE='TestLang',
            HTTP_ACCEPT_ENCODING='TestEnc',
            HTTP_ACCEPT='TestAccept'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        # Components should appear in order: UA, Lang, Enc, Accept
        ua_pos = fingerprint.find('UA:')
        lang_pos = fingerprint.find('Lang:')
        enc_pos = fingerprint.find('Enc:')
        accept_pos = fingerprint.find('Accept:')
        
        assert ua_pos < lang_pos < enc_pos < accept_pos
        
    def test_fingerprint_with_none_request(self):
        """Test fingerprint generation with None request."""
        fingerprint = extract_device_fingerprint(None)
        
        assert fingerprint == "unknown"
        
    def test_fingerprint_real_world_chrome(self):
        """Test fingerprint with real-world Chrome user agent."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9',
            HTTP_ACCEPT_ENCODING='gzip, deflate, br',
            HTTP_ACCEPT='text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        # Should contain identifiable Chrome information
        assert 'Chrome/120.0.0.0' in fingerprint
        assert len(fingerprint) <= 512
        
    def test_fingerprint_real_world_firefox(self):
        """Test fingerprint with real-world Firefox user agent."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.5',
            HTTP_ACCEPT_ENCODING='gzip, deflate, br',
            HTTP_ACCEPT='text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        # Should contain identifiable Firefox information
        assert 'Firefox/121.0' in fingerprint
        assert len(fingerprint) <= 512
        
    def test_fingerprint_real_world_safari(self):
        """Test fingerprint with real-world Safari user agent."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9',
            HTTP_ACCEPT_ENCODING='gzip, deflate, br',
            HTTP_ACCEPT='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        # Should contain identifiable Safari information
        assert 'Safari/605.1.15' in fingerprint
        assert len(fingerprint) <= 512
        
    def test_fingerprint_real_world_mobile_chrome(self):
        """Test fingerprint with real-world mobile Chrome user agent."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.43 Mobile Safari/537.36',
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9',
            HTTP_ACCEPT_ENCODING='gzip, deflate, br',
            HTTP_ACCEPT='text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        # Should contain mobile indicators
        assert 'Mobile' in fingerprint
        assert 'Android' in fingerprint
        assert len(fingerprint) <= 512
        
    def test_fingerprint_real_world_ios_safari(self):
        """Test fingerprint with real-world iOS Safari user agent."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9',
            HTTP_ACCEPT_ENCODING='gzip, deflate, br',
            HTTP_ACCEPT='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        # Should contain iOS indicators
        assert 'iPhone' in fingerprint
        assert len(fingerprint) <= 512
        
    def test_fingerprint_special_characters_in_headers(self):
        """Test fingerprint handles special characters in headers."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Test/1.0 (Special; Chars: @#$%)',
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        # Should handle special characters without errors
        assert '@#$%' in fingerprint
        assert len(fingerprint) <= 512
        
    def test_fingerprint_unicode_characters_in_headers(self):
        """Test fingerprint handles unicode characters in headers."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 测试',
            HTTP_ACCEPT_LANGUAGE='zh-CN,zh;q=0.9'
        )
        
        fingerprint = extract_device_fingerprint(request)
        
        # Should handle unicode without errors
        assert '测试' in fingerprint or len(fingerprint) > 0
        assert len(fingerprint) <= 512


class TestDeviceFingerprintingIntegration:
    """Integration tests for device fingerprinting in the context of voting models."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.factory = RequestFactory()
        
    def test_fingerprint_fits_in_model_field_length(self):
        """Test that fingerprint length matches model field max_length (512 for AuditLog, 255 for others)."""
        from voting.models import VoteAttempt, AuditLog
        
        # Check AuditLog field (512 chars)
        audit_field = AuditLog._meta.get_field('device_fingerprint')
        assert audit_field.max_length == 512
        
        # Check VoteAttempt field (255 chars) - Note: device_identifier
        attempt_field = VoteAttempt._meta.get_field('device_identifier')
        assert attempt_field.max_length == 255
        
        # Generate a fingerprint
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9'
        )
        fingerprint = extract_device_fingerprint(request)
        
        # Should fit in both fields
        assert len(fingerprint) <= 512  # AuditLog
        # For VoteAttempt, might need truncation in application code if > 255
        
    def test_multiple_requests_same_device_same_fingerprint(self):
        """Test that multiple requests from same device produce same fingerprint."""
        # Simulate same device making multiple requests
        fingerprints = []
        
        for _ in range(5):
            request = self.factory.get(
                '/',
                HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9',
                HTTP_ACCEPT_ENCODING='gzip, deflate, br',
                HTTP_ACCEPT='text/html,application/xhtml+xml'
            )
            fingerprints.append(extract_device_fingerprint(request))
        
        # All fingerprints should be identical
        assert len(set(fingerprints)) == 1
        
    def test_different_devices_different_fingerprints(self):
        """Test that requests from different devices produce different fingerprints."""
        # Device 1: Chrome on Windows
        request1 = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9'
        )
        
        # Device 2: Firefox on Linux
        request2 = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0',
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.5'
        )
        
        # Device 3: Safari on macOS
        request3 = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15',
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9'
        )
        
        fingerprint1 = extract_device_fingerprint(request1)
        fingerprint2 = extract_device_fingerprint(request2)
        fingerprint3 = extract_device_fingerprint(request3)
        
        # All should be different
        assert fingerprint1 != fingerprint2
        assert fingerprint1 != fingerprint3
        assert fingerprint2 != fingerprint3
        
    def test_fingerprint_stability_across_many_calls(self):
        """Test that fingerprint remains stable across many calls."""
        request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 Test',
            HTTP_ACCEPT_LANGUAGE='en-US'
        )
        
        first_fingerprint = extract_device_fingerprint(request)
        
        # Call 100 times and verify consistency
        for _ in range(100):
            assert extract_device_fingerprint(request) == first_fingerprint
            
    def test_fingerprint_useful_for_fraud_detection(self):
        """Test that fingerprint captures enough detail for fraud detection."""
        # Legitimate user with stable headers
        legitimate_request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
            HTTP_ACCEPT_LANGUAGE='en-US,en;q=0.9',
            HTTP_ACCEPT_ENCODING='gzip, deflate, br',
            HTTP_ACCEPT='text/html,application/xhtml+xml'
        )
        
        # Bot/scraper with minimal headers
        bot_request = self.factory.get(
            '/',
            HTTP_USER_AGENT='Python-urllib/3.11'
        )
        
        legitimate_fp = extract_device_fingerprint(legitimate_request)
        bot_fp = extract_device_fingerprint(bot_request)
        
        # Should be distinguishable
        assert legitimate_fp != bot_fp
        
        # Legitimate request should have more information
        assert len(legitimate_fp) > len(bot_fp)
        
    def test_fingerprint_empty_vs_minimal_headers(self):
        """Test distinguishing between no headers and minimal headers."""
        # No headers at all
        no_headers_request = self.factory.get('/')
        
        # Minimal headers (just user agent)
        minimal_request = self.factory.get(
            '/',
            HTTP_USER_AGENT='curl/7.68.0'
        )
        
        no_headers_fp = extract_device_fingerprint(no_headers_request)
        minimal_fp = extract_device_fingerprint(minimal_request)
        
        assert no_headers_fp == "unknown"
        assert minimal_fp != "unknown"
        assert 'curl' in minimal_fp
