import pytest
from fasthtml.common import *
from starlette.testclient import TestClient
import os
import tempfile
import shutil

# Import the app
from app import app, hash_password

@pytest.fixture
def client():
    """Create a test client with a temporary database"""
    # Create a temp directory for the test database
    test_dir = tempfile.mkdtemp()
    test_db = os.path.join(test_dir, 'test_users.db')
    
    # Monkey patch the database path
    import app as app_module
    original_db = app_module.db
    app_module.db = database(test_db)
    app_module.users = app_module.db.t.users
    if app_module.users not in app_module.db.t:
        app_module.users.create(dict(username=str, password=str), pk='username')
    
    client = TestClient(app)
    yield client
    
    # Restore and cleanup
    app_module.db = original_db
    app_module.users = original_db.t.users
    shutil.rmtree(test_dir, ignore_errors=True)

def test_homepage_not_logged_in(client):
    """Test homepage shows 'hello, world' when not logged in"""
    response = client.get("/")
    assert response.status_code == 200
    assert "hello, world" in response.text
    assert "Login" in response.text
    assert "Register" in response.text

def test_login_before_users_registered(client):
    """Test login fails when no users exist"""
    response = client.post("/login", data={
        "username": "nonexistent",
        "password": "password123"
    }, follow_redirects=False)
    assert response.status_code == 200
    assert "Invalid username or password" in response.text

def test_register_new_user(client):
    """Test successful user registration"""
    response = client.post("/register", data={
        "username": "testuser",
        "password": "testpass123"
    }, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"

def test_register_duplicate_username(client):
    """Test registering with an existing username fails"""
    # First registration
    client.post("/register", data={
        "username": "duplicate",
        "password": "password123"
    })
    
    # Try to register same username again
    response = client.post("/register", data={
        "username": "duplicate",
        "password": "different456"
    }, follow_redirects=False)
    assert response.status_code == 200
    assert "Username already exists" in response.text

def test_login_success(client):
    """Test successful login"""
    # Register a user first
    client.post("/register", data={
        "username": "logintest",
        "password": "testpass123"
    })
    
    # Logout to clear session
    client.get("/logout")
    
    # Login
    response = client.post("/login", data={
        "username": "logintest",
        "password": "testpass123"
    }, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"

def test_login_wrong_password(client):
    """Test login fails with wrong password"""
    # Register a user first
    client.post("/register", data={
        "username": "passtest",
        "password": "correct123"
    })
    
    # Try to login with wrong password
    response = client.post("/login", data={
        "username": "passtest",
        "password": "wrong456"
    }, follow_redirects=False)
    assert response.status_code == 200
    assert "Invalid username or password" in response.text

def test_homepage_logged_in(client):
    """Test homepage shows username when logged in"""
    # Register and login
    client.post("/register", data={
        "username": "hellotest",
        "password": "testpass123"
    }, follow_redirects=True)
    
    # Check homepage
    response = client.get("/")
    assert response.status_code == 200
    assert "hello, hellotest" in response.text
    assert "Logout" in response.text

def test_logout(client):
    """Test logout functionality"""
    # Register a user
    client.post("/register", data={
        "username": "logouttest",
        "password": "testpass123"
    })
    
    # Logout
    response = client.get("/logout", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    
    # Check we're logged out
    response = client.get("/")
    assert "hello, world" in response.text
    assert "hello, logouttest" not in response.text

def test_password_hashing(client):
    """Test that passwords are hashed, not stored in plain text"""
    username = "hashtest"
    password = "mypassword123"
    
    # Register user
    client.post("/register", data={
        "username": username,
        "password": password
    })
    
    # Check database directly
    from app import users
    user = users.get(username)
    assert user['password'] != password
    assert user['password'] == hash_password(password)
