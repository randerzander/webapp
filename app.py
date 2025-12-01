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
import asyncio
from threading import Thread

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
        
        # Generate unique ID for this request
        import uuid
        request_id = str(uuid.uuid4())
        
        # Store content for async summary generation
        summary_cache[request_id] = {
            'status': 'pending',
            'markdown': markdown_content[:4000]
        }
        
        # Start async summary generation
        def generate_summary():
            try:
                logging.info("Starting LLM summary call")
                llm_start = time.time()
                client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=os.environ.get("OPENROUTER_API_KEY", "")
                )
                
                model = os.environ.get("OPENROUTER_MODEL", "x-ai/grok-4.1-fast:free")
                
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "user", "content": f"Summarize this article in 2-3 sentences:\n\n{summary_cache[request_id]['markdown']}"}
                    ]
                )
                summary = completion.choices[0].message.content
                llm_time = time.time() - llm_start
                logging.info(f"LLM summary call complete in {llm_time:.2f}s")
                
                summary_cache[request_id] = {
                    'status': 'complete',
                    'summary': summary,
                    'llm_time': llm_time
                }
            except Exception as e:
                logging.error(f"LLM summary failed: {str(e)}")
                summary_cache[request_id] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        Thread(target=generate_summary, daemon=True).start()
        
        if format == "html":
            # Render markdown as HTML
            import markdown
            html_content = markdown.markdown(markdown_content)
            return Titled("Processed Article",
                Script(src="https://unpkg.com/htmx.org@1.9.10"),
                H2(article.get('title', 'Article Content')),
                P(f"Length: {char_count:,} characters, ~{token_count:,} tokens", style="color: #666; font-size: 0.9em;"),
                P(f"Timing: Request {request_time:.2f}s | Readability {readability_time:.2f}s", style="color: #666; font-size: 0.9em;"),
                Div(id="summary-container", hx_get=f"/get-summary/{request_id}", hx_trigger="load", hx_swap="outerHTML")(
                    P("⏳ Generating summary...", style="color: #666; font-style: italic;")
                ),
                NotStr(html_content),
                A("Back to home", href="/"))
        else:
            # Display as markdown
            return Titled("Processed Article",
                Script(src="https://unpkg.com/htmx.org@1.9.10"),
                Style("pre { white-space: pre-wrap; background: #f5f5f5; padding: 1em; border-radius: 5px; }"),
                H2(article.get('title', 'Article Content')),
                P(f"Length: {char_count:,} characters, ~{token_count:,} tokens", style="color: #666; font-size: 0.9em;"),
                P(f"Timing: Request {request_time:.2f}s | Readability {readability_time:.2f}s", style="color: #666; font-size: 0.9em;"),
                Div(id="summary-container", hx_get=f"/get-summary/{request_id}", hx_trigger="load", hx_swap="outerHTML")(
                    P("⏳ Generating summary...", style="color: #666; font-style: italic;")
                ),
                Pre(markdown_content),
                A("Back to home", href="/"))
    except Exception as e:
        return Titled("Error",
            P(f"Error processing URL: {str(e)}", style="color: red"),
            A("Back to home", href="/"))

# Store summary requests
summary_cache = {}

@rt("/get-summary/{request_id}")
def get(request_id: str):
    # Check if summary is ready
    if request_id not in summary_cache:
        return Div(id="summary-container")(
            P("Summary expired", style="color: #666; font-style: italic;")
        )
    
    result = summary_cache[request_id]
    
    if result['status'] == 'complete':
        summary_div = Div(id="summary-container")(
            H3("Summary"),
            P(result['summary'], style="background: #f0f8ff; padding: 1em; border-radius: 5px; border-left: 4px solid #4a90e2;"),
            P(f"LLM timing: {result['llm_time']:.2f}s", style="color: #666; font-size: 0.9em;")
        )
        del summary_cache[request_id]
        return summary_div
    elif result['status'] == 'error':
        error_div = Div(id="summary-container")(
            H3("Summary"),
            P(f"Summary unavailable: {result['error']}", style="color: #dc3545;")
        )
        del summary_cache[request_id]
        return error_div
    else:
        # Still processing, poll again
        return Div(id="summary-container", hx_get=f"/get-summary/{request_id}", hx_trigger="load delay:1s", hx_swap="outerHTML")(
            P("⏳ Generating summary...", style="color: #666; font-style: italic;")
        )

@rt("/logout")
def get(sess):
    sess.clear()
    return RedirectResponse("/", status_code=303)

serve(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
