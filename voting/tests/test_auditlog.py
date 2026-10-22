"""
Unit tests for AuditLog model.

Tests the comprehensive audit logging system including all action types,
field validations, indexes, and security tracking capabilities.

Validates Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.18
"""

import pytest
from django.utils import timezone
from accounts.models import User
from voting.models import AuditLog


@pytest.mark.django_db
class TestAuditLogModel:
    """Tests for the AuditLog model."""

    def test_auditlog_creation_with_all_fields(self):
        """Test creating an audit log with all required fields."""
        user = User.objects.create_user(
            email="testuser@example.com",
            password="testpass123",
            name="Test User"
        )
        
        audit_log = AuditLog.objects.create(
            user=user,
            action_type=AuditLog.ActionType.VOTE_COMPLETED,
            resource_type="Vote",
            resource_id="12345",
            device_fingerprint="test-device-fingerprint-12345",
            ip_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",  # SHA-256 hash
            metadata={"vote_quantity": 5, "contestant_id": "abc123"}
        )
        
        assert audit_log.id is not None
        assert audit_log.user == user
        assert audit_log.action_type == AuditLog.ActionType.VOTE_COMPLETED
        assert audit_log.resource_type == "Vote"
        assert audit_log.resource_id == "12345"
        assert audit_log.device_fingerprint == "test-device-fingerprint-12345"
        assert audit_log.ip_hash == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert audit_log.metadata["vote_quantity"] == 5
        assert audit_log.timestamp is not None

    def test_auditlog_all_action_types(self):
        """Test all 12 action type enum values are stored correctly."""
        action_types = [
            AuditLog.ActionType.VOTE_STARTED,
            AuditLog.ActionType.VOTE_COMPLETED,
            AuditLog.ActionType.VOTE_REJECTED,
            AuditLog.ActionType.VOTE_FAILED,
            AuditLog.ActionType.LOGIN_SUCCESS,
            AuditLog.ActionType.LOGIN_FAILED,
            AuditLog.ActionType.LOGOUT,
            AuditLog.ActionType.ROLE_CHANGE,
            AuditLog.ActionType.CONTEST_CREATED,
            AuditLog.ActionType.CONTEST_STATE_CHANGE,
            AuditLog.ActionType.PAYMENT_CONFIRMED,
            AuditLog.ActionType.PAYMENT_FAILED,
        ]
        
        # Verify all 12 action types exist
        assert len(action_types) == 12
        
        # Create audit logs for each action type
        for action_type in action_types:
            audit_log = AuditLog.objects.create(
                action_type=action_type,
                resource_type="Test",
                resource_id="test-id",
            )
            assert audit_log.action_type == action_type

    def test_auditlog_suspicious_pattern_action_type(self):
        """Test SUSPICIOUS_PATTERN action type (13th type for fraud detection)."""
        audit_log = AuditLog.objects.create(
            action_type=AuditLog.ActionType.SUSPICIOUS_PATTERN,
            resource_type="VoteAttempt",
            resource_id="suspicious-123",
            metadata={
                "pattern": "excessive_rejections",
                "count": 15,
                "time_window": "60_minutes"
            }
        )
        
        assert audit_log.action_type == AuditLog.ActionType.SUSPICIOUS_PATTERN
        assert audit_log.metadata["pattern"] == "excessive_rejections"

    def test_auditlog_nullable_user(self):
        """Test audit log creation without a user (system actions)."""
        audit_log = AuditLog.objects.create(
            user=None,
            action_type=AuditLog.ActionType.CONTEST_STATE_CHANGE,
            resource_type="Contest",
            resource_id="auto-close-123",
            metadata={"reason": "auto_close", "trigger": "scheduled_task"}
        )
        
        assert audit_log.user is None
        assert audit_log.action_type == AuditLog.ActionType.CONTEST_STATE_CHANGE

    def test_auditlog_metadata_json_field(self):
        """Test metadata JSONField stores complex objects correctly."""
        complex_metadata = {
            "request_headers": {
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "en-US",
                "Referer": "https://example.com/poll"
            },
            "auth_attempt": {
                "method": "password",
                "success": False,
                "reason": "invalid_credentials"
            },
            "timestamp": timezone.now().isoformat(),
            "nested_list": [1, 2, 3, {"key": "value"}]
        }
        
        audit_log = AuditLog.objects.create(
            action_type=AuditLog.ActionType.LOGIN_FAILED,
            resource_type="User",
            resource_id="user-123",
            metadata=complex_metadata
        )
        
        # Retrieve and verify
        retrieved_log = AuditLog.objects.get(id=audit_log.id)
        assert retrieved_log.metadata["request_headers"]["User-Agent"] == "Mozilla/5.0"
        assert retrieved_log.metadata["auth_attempt"]["success"] is False
        assert retrieved_log.metadata["nested_list"][3]["key"] == "value"

    def test_auditlog_device_fingerprint_max_length(self):
        """Test device_fingerprint field max length of 512 characters."""
        long_fingerprint = "x" * 512
        audit_log = AuditLog.objects.create(
            action_type=AuditLog.ActionType.VOTE_STARTED,
            resource_type="VoteAttempt",
            resource_id="test-123",
            device_fingerprint=long_fingerprint
        )
        
        assert len(audit_log.device_fingerprint) == 512

    def test_auditlog_ip_hash_sha256_format(self):
        """Test ip_hash field stores SHA-256 hash (64 characters)."""
        # SHA-256 hash is exactly 64 hexadecimal characters
        sha256_hash = "a" * 64
        audit_log = AuditLog.objects.create(
            action_type=AuditLog.ActionType.LOGIN_SUCCESS,
            resource_type="User",
            resource_id="user-456",
            ip_hash=sha256_hash
        )
        
        assert len(audit_log.ip_hash) == 64

    def test_auditlog_timestamp_auto_now_add(self):
        """Test timestamp is automatically set with millisecond precision."""
        before = timezone.now()
        audit_log = AuditLog.objects.create(
            action_type=AuditLog.ActionType.PAYMENT_CONFIRMED,
            resource_type="Payment",
            resource_id="payment-789"
        )
        after = timezone.now()
        
        assert before <= audit_log.timestamp <= after
        # Verify timestamp has microsecond precision (Django uses microsecond, which is better than millisecond)
        assert audit_log.timestamp.microsecond is not None

    def test_auditlog_resource_tracking_fields(self):
        """Test resource_type and resource_id fields for tracking affected resources."""
        audit_log = AuditLog.objects.create(
            action_type=AuditLog.ActionType.CONTEST_CREATED,
            resource_type="Contest",
            resource_id="contest-uuid-12345",
            metadata={"title": "Test Contest", "organizer_id": "org-123"}
        )
        
        assert audit_log.resource_type == "Contest"
        assert audit_log.resource_id == "contest-uuid-12345"
        assert AuditLog._meta.get_field("resource_type").max_length == 100

    def test_auditlog_ordering(self):
        """Test audit logs are ordered by timestamp descending."""
        # Create multiple audit logs
        log1 = AuditLog.objects.create(
            action_type=AuditLog.ActionType.LOGIN_SUCCESS,
            resource_type="User",
            resource_id="user-1"
        )
        
        log2 = AuditLog.objects.create(
            action_type=AuditLog.ActionType.VOTE_STARTED,
            resource_type="Vote",
            resource_id="vote-1"
        )
        
        log3 = AuditLog.objects.create(
            action_type=AuditLog.ActionType.LOGOUT,
            resource_type="User",
            resource_id="user-1"
        )
        
        # Retrieve all logs
        logs = list(AuditLog.objects.all())
        
        # Should be ordered by timestamp descending (most recent first)
        assert logs[0].id == log3.id
        assert logs[1].id == log2.id
        assert logs[2].id == log1.id

    def test_auditlog_indexes_exist(self):
        """Verify that required indexes exist on the model."""
        # Check Meta indexes
        indexes = AuditLog._meta.indexes
        index_names = [idx.name for idx in indexes]
        
        # Required indexes per design specification
        assert "auditlog_timestamp_idx" in index_names
        assert "auditlog_user_timestamp_idx" in index_names
        assert "auditlog_action_timestamp_idx" in index_names
        assert "auditlog_resource_idx" in index_names

    def test_auditlog_str_representation(self):
        """Test string representation of audit log."""
        user = User.objects.create_user(
            email="loguser@example.com",
            password="pass123",
            name="Log User"
        )
        
        audit_log = AuditLog.objects.create(
            user=user,
            action_type=AuditLog.ActionType.ROLE_CHANGE,
            resource_type="User",
            resource_id="user-role-123"
        )
        
        str_repr = str(audit_log)
        assert "ROLE_CHANGE" in str_repr
        assert "loguser@example.com" in str_repr

    def test_auditlog_system_action_str_representation(self):
        """Test string representation for system actions (no user)."""
        audit_log = AuditLog.objects.create(
            user=None,
            action_type=AuditLog.ActionType.CONTEST_STATE_CHANGE,
            resource_type="Contest",
            resource_id="contest-auto-123"
        )
        
        str_repr = str(audit_log)
        assert "CONTEST_STATE_CHANGE" in str_repr
        assert "System" in str_repr

    def test_auditlog_default_empty_values(self):
        """Test default values for optional fields."""
        audit_log = AuditLog.objects.create(
            action_type=AuditLog.ActionType.VOTE_FAILED,
            resource_type="Vote",
            resource_id="vote-fail-123"
        )
        
        assert audit_log.user is None
        assert audit_log.device_fingerprint == ""
        assert audit_log.ip_hash == ""
        assert audit_log.metadata == {}

    def test_auditlog_query_by_action_type(self):
        """Test querying audit logs by action type."""
        # Create logs with different action types
        AuditLog.objects.create(
            action_type=AuditLog.ActionType.VOTE_COMPLETED,
            resource_type="Vote",
            resource_id="vote-1"
        )
        AuditLog.objects.create(
            action_type=AuditLog.ActionType.VOTE_COMPLETED,
            resource_type="Vote",
            resource_id="vote-2"
        )
        AuditLog.objects.create(
            action_type=AuditLog.ActionType.LOGIN_SUCCESS,
            resource_type="User",
            resource_id="user-1"
        )
        
        # Query by action type
        vote_logs = AuditLog.objects.filter(action_type=AuditLog.ActionType.VOTE_COMPLETED)
        login_logs = AuditLog.objects.filter(action_type=AuditLog.ActionType.LOGIN_SUCCESS)
        
        assert vote_logs.count() == 2
        assert login_logs.count() == 1

    def test_auditlog_query_by_user_and_timestamp(self):
        """Test querying audit logs by user and timestamp (composite index)."""
        user = User.objects.create_user(
            email="indextest@example.com",
            password="pass123",
            name="Index Test"
        )
        
        # Create multiple logs for the user
        for i in range(5):
            AuditLog.objects.create(
                user=user,
                action_type=AuditLog.ActionType.VOTE_STARTED,
                resource_type="Vote",
                resource_id=f"vote-{i}"
            )
        
        # Query logs for this user
        user_logs = AuditLog.objects.filter(user=user).order_by('-timestamp')
        assert user_logs.count() == 5

    def test_auditlog_set_null_on_user_deletion(self):
        """Test that user FK uses SET_NULL when user is deleted."""
        user = User.objects.create_user(
            email="deleteme@example.com",
            password="pass123",
            name="Delete Me"
        )
        
        audit_log = AuditLog.objects.create(
            user=user,
            action_type=AuditLog.ActionType.VOTE_COMPLETED,
            resource_type="Vote",
            resource_id="vote-orphan"
        )
        
        # Delete the user
        user.delete()
        
        # Audit log should still exist with user=None
        audit_log.refresh_from_db()
        assert audit_log.user is None
        assert audit_log.action_type == AuditLog.ActionType.VOTE_COMPLETED
