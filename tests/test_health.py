"""Tests for health check endpoint."""
import pytest


class TestHealthCheck:
    """Test health check endpoint."""
    
    def test_health_check_success(self, client, db_session):
        """Test successful health check."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["ok", "degraded"]
        assert "database" in data
        assert "redis" in data
    
    def test_health_check_database_ok(self, client):
        """Test database connectivity in health check."""
        response = client.get("/health")
        data = response.json()
        assert data["database"] == "ok"
    
    def test_root_endpoint(self, client):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Market Intelligence Trading Signal System"
        assert data["version"] == "1.0.0"
        assert data["status"] == "running"
