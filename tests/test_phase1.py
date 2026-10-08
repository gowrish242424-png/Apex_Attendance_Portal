import unittest
import json
from app import create_app
from app.extensions import db

class Phase1SetupTestCase(unittest.TestCase):
    def setUp(self):
        """Set up test environment."""
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        """Clean up test environment."""
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_app_creation(self):
        """Test application factory creates an active app instance."""
        self.assertIsNotNone(self.app)
        self.assertTrue(self.app.config['TESTING'])

    def test_home_page_returns_200(self):
        """Test GET / returns HTTP 200 and renders expected content."""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Advanced Attendance Management System', response.data)
        self.assertIn(b'Phase 1: Project Setup', response.data)

    def test_health_check_endpoint(self):
        """Test GET /health returns 200 and database is connected."""
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'healthy')
        self.assertEqual(data.get('database'), 'connected')
        self.assertEqual(data.get('version'), '1.0.0')

if __name__ == '__main__':
    unittest.main()
