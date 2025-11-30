import pytest
from fasthtml.common import *
from starlette.testclient import TestClient
import os
import tempfile
import shutil

@pytest.fixture
def client():
    """Create a test client with a temporary database"""
    # Create a temp directory for the test database
    test_dir = tempfile.mkdtemp()
    test_db = os.path.join(test_dir, 'test_users.db')
    
    # Import fresh app module
    import app as app_module
    from importlib import reload
    
    # Store original db
    original_db_path = 'users.db'
    
    # Create new test database
    test_db_obj = database(test_db)
    test_users = test_db_obj.t.users
    if test_users not in test_db_obj.t:
        test_users.create(dict(username=str, password=str), pk='username')
    
    # Patch the app module
    app_module.db = test_db_obj
    app_module.users = test_users
    
    client = TestClient(app_module.app)
    yield client
    
    # Cleanup
    try:
        shutil.rmtree(test_dir, ignore_errors=True)
    except:
        pass
    
    # Restore original database for app module
    app_module.db = database(original_db_path)
    app_module.users = app_module.db.t.users

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
    import app as app_module
    
    username = "hashtest"
    password = "mypassword123"
    
    # Register user
    client.post("/register", data={
        "username": username,
        "password": password
    })
    
    # Check database directly
    user = app_module.users.get(username)
    assert user['password'] != password
    assert user['password'] == app_module.hash_password(password)

def test_process_url_logged_in(client):
    """Test processing a URL after logging in"""
    # Register and login
    client.post("/register", data={
        "username": "urltest",
        "password": "testpass123"
    }, follow_redirects=True)
    
    # Submit a test URL with markdown format
    response = client.post("/process-url", data={
        "url": "https://example.com",
        "format": "markdown"
    }, follow_redirects=False)
    
    assert response.status_code == 200
    assert "Processed Article" in response.text or "Article Content" in response.text

def test_process_url_html_format(client):
    """Test processing a URL with HTML format"""
    # Register and login
    client.post("/register", data={
        "username": "htmltest",
        "password": "testpass123"
    }, follow_redirects=True)
    
    # Submit a test URL with html format
    response = client.post("/process-url", data={
        "url": "https://example.com",
        "format": "html"
    }, follow_redirects=False)
    
    assert response.status_code == 200
    assert "Processed Article" in response.text or "Article Content" in response.text

def test_process_url_not_logged_in(client):
    """Test that processing URL requires login"""
    response = client.post("/process-url", data={
        "url": "https://example.com",
        "format": "markdown"
    }, follow_redirects=False)
    
    # Should redirect to login
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
