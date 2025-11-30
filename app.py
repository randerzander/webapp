from fasthtml.common import *
from sqlite3 import IntegrityError
import apsw
import hashlib
import os

# Database setup
db = database('users.db')
users = db.t.users
if users not in db.t:
    users.create(dict(username=str, password=str), pk='username')

# App with sessions
app, rt = fast_app(secret_key='secret-key-change-in-production')

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

@rt("/")
def get(sess):
    username = sess.get('username')
    if username:
        return Titled("Home", 
            P(f"hello, {username}"),
            A("Logout", href="/logout"))
    return Titled("Home",
        P("hello, world"),
        A("Login", href="/login"), " | ",
        A("Register", href="/register"))

@rt("/register")
def get():
    return Titled("Register",
        Form(method="post", action="/register")(
            Input(name="username", placeholder="Username", required=True),
            Input(name="password", type="password", placeholder="Password", required=True),
            Button("Register")
        ),
        A("Back to home", href="/"))

@rt("/register")
def post(username: str, password: str, sess):
    try:
        users.insert(dict(username=username, password=hash_password(password)))
        sess['username'] = username
        return RedirectResponse("/", status_code=303)
    except (IntegrityError, apsw.ConstraintError):
        return Titled("Register",
            P("Username already exists", style="color: red"),
            Form(method="post", action="/register")(
                Input(name="username", placeholder="Username", required=True),
                Input(name="password", type="password", placeholder="Password", required=True),
                Button("Register")
            ),
            A("Back to home", href="/"))

@rt("/login")
def get():
    return Titled("Login",
        Form(method="post", action="/login")(
            Input(name="username", placeholder="Username", required=True),
            Input(name="password", type="password", placeholder="Password", required=True),
            Button("Login")
        ),
        A("Back to home", href="/"))

@rt("/login")
def post(username: str, password: str, sess):
    try:
        user = users.get(username)
        if user and user['password'] == hash_password(password):
            sess['username'] = username
            return RedirectResponse("/", status_code=303)
    except:
        pass
    return Titled("Login",
        P("Invalid username or password", style="color: red"),
        Form(method="post", action="/login")(
            Input(name="username", placeholder="Username", required=True),
            Input(name="password", type="password", placeholder="Password", required=True),
            Button("Login")
        ),
        A("Back to home", href="/"))

@rt("/logout")
def get(sess):
    sess.clear()
    return RedirectResponse("/", status_code=303)

serve(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
