from fasthtml.common import *
from sqlite3 import IntegrityError
import apsw
import hashlib
import os
from readability import Readability
import requests
from bs4 import BeautifulSoup
import html2text
from openai import OpenAI
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
            Form(method="post", action="/process-url")(
                Input(name="url", placeholder="Enter URL to process", required=True, type="url"),
                Div(
                    Label(Input(type="radio", name="format", value="markdown", checked=True), "Markdown"),
                    Label(Input(type="radio", name="format", value="html"), "Rendered HTML")
                ),
                Button("Process URL")
            ),
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

@rt("/process-url")
def post(url: str, format: str, sess):
    username = sess.get('username')
    if not username:
        return RedirectResponse("/login", status_code=303)
    
    try:
        logging.info(f"Making request to URL: {url}")
        request_start = time.time()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        request_time = time.time() - request_start
        content_length = len(response.content)
        logging.info(f"Content retrieved: {content_length:,} bytes in {request_time:.2f}s")
        
        logging.info("Starting readability processing")
        readability_start = time.time()
        doc = BeautifulSoup(response.text, 'lxml')
        
        r = Readability(doc, url=url)
        article = r.parse()
        readability_time = time.time() - readability_start
        logging.info(f"Readability processing complete in {readability_time:.2f}s")
        
        h = html2text.HTML2Text()
        markdown_content = h.handle(article['content'])
        
        char_count = len(markdown_content)
        token_count = int(char_count / 4.5)
        
        # Generate summary using OpenRouter
        logging.info("Starting LLM summary call")
        llm_start = time.time()
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ.get("OPENROUTER_API_KEY", "")
        )
        
        model = os.environ.get("OPENROUTER_MODEL", "x-ai/grok-4.1-fast:free")
        
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "user", "content": f"Summarize this article in 2-3 sentences:\n\n{markdown_content[:4000]}"}
                ]
            )
            summary = completion.choices[0].message.content
            llm_time = time.time() - llm_start
            logging.info(f"LLM summary call complete in {llm_time:.2f}s")
        except Exception as e:
            llm_time = time.time() - llm_start
            logging.error(f"LLM summary failed: {str(e)}")
            summary = f"Summary unavailable: {str(e)}"
        
        if format == "html":
            # Render markdown as HTML
            import markdown
            html_content = markdown.markdown(markdown_content)
            return Titled("Processed Article",
                H2(article.get('title', 'Article Content')),
                P(f"Length: {char_count:,} characters, ~{token_count:,} tokens", style="color: #666; font-size: 0.9em;"),
                P(f"Timing: Request {request_time:.2f}s | Readability {readability_time:.2f}s | LLM {llm_time:.2f}s", style="color: #666; font-size: 0.9em;"),
                Div(
                    H3("Summary"),
                    P(summary, style="background: #f0f8ff; padding: 1em; border-radius: 5px; border-left: 4px solid #4a90e2;")
                ),
                NotStr(html_content),
                A("Back to home", href="/"))
        else:
            # Display as markdown
            return Titled("Processed Article",
                Style("pre { white-space: pre-wrap; background: #f5f5f5; padding: 1em; border-radius: 5px; }"),
                H2(article.get('title', 'Article Content')),
                P(f"Length: {char_count:,} characters, ~{token_count:,} tokens", style="color: #666; font-size: 0.9em;"),
                P(f"Timing: Request {request_time:.2f}s | Readability {readability_time:.2f}s | LLM {llm_time:.2f}s", style="color: #666; font-size: 0.9em;"),
                Div(
                    H3("Summary"),
                    P(summary, style="background: #f0f8ff; padding: 1em; border-radius: 5px; border-left: 4px solid #4a90e2;")
                ),
                Pre(markdown_content),
                A("Back to home", href="/"))
    except Exception as e:
        return Titled("Error",
            P(f"Error processing URL: {str(e)}", style="color: red"),
            A("Back to home", href="/"))

@rt("/logout")
def get(sess):
    sess.clear()
    return RedirectResponse("/", status_code=303)

serve(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
