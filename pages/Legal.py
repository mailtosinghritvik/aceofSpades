import streamlit as st
from openai import OpenAI
import os
from datetime import datetime, timezone, timedelta
import time
import imaplib
import json
from imap_tools import MailBox, AND
from supabase import create_client
import tempfile
from ics import Calendar, Event
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import re
from bs4 import BeautifulSoup
from fpdf import FPDF
import html2text
import base64
import io
from PIL import Image
import unicodedata

# Email configuration
email_sender = st.secrets["EMAIL_SENDER"]  # Use Streamlit secrets for securi
sender_password = st.secrets["EMAIL_PASSWORD2"]  # Use Streamlit secrets for security
EMAIL_RECEIVER = "mailtosinghritvik@gmail.com"

# Initialize Supabase client
try:
    with open('.streamlit/secrets.toml') as f:
        config = json.load(f)
        supabase_url = config.get('SUPABASE_URL')
        supabase_key = config.get('SUPABASE_KEY')
except:
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]
supabase = create_client(supabase_url, supabase_key)

# Initialize session state

try:
    with open('../streamlit/secrets.toml') as f:
        config = json.load(f)
        email = config.get('EMAIL_ADDRESS')
        password = config.get('EMAIL_PASSWORD')
except:
    email = st.secrets["EMAIL_ADDRESS"]
    password = st.secrets["EMAIL_PASSWORD"]

if 'threads' not in st.session_state:
    st.session_state.threads = {}

if 'current_thread_id' not in st.session_state:
    st.session_state.current_thread_id = None
if 'current_thread_name' not in st.session_state:
    st.session_state.current_thread_name = None
if 'messages' not in st.session_state:
    st.session_state.messages = []

# Create upload directory
UPLOAD_FOLDER = os.path.join(os.getcwd(), "temp")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_client():
    """Get or create OpenAI client"""
    if 'openai_client' not in st.session_state:
        try:
            st.session_state.openai_client = OpenAI(
                api_key=os.getenv('OPENAI_API_KEY'),
                max_retries=3,
                timeout=20.0
            )
        except Exception as e:
            st.error(f"Error initializing OpenAI client: {str(e)}")
            return None
    return st.session_state.openai_client

def create_thread(name=""):
    """Create a new thread with OpenAI"""
    try:
        client = get_client()
        if not client:
            return None, None
            
        # Set default name if not provided
        if not name or name.strip() == '':
            name = f"Legal Thread {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        # Create thread using OpenAI API
        thread = client.beta.threads.create()
        
        # Store thread info
        st.session_state.threads[thread.id] = {
            'thread': thread,
            'name': name
        }
        
        return thread.id, name
    except Exception as e:
        st.error(f"Error creating thread: {str(e)}")
        return None, None

def delete_thread(thread_id):
    """Delete a thread"""
    try:
        if thread_id in st.session_state.threads:
            del st.session_state.threads[thread_id]
            if st.session_state.current_thread_id == thread_id:
                st.session_state.current_thread_id = None
                st.session_state.current_thread_name = None
            return True
        return False
    except Exception as e:
        st.error(f"Error deleting thread: {str(e)}")
        return False

def get_threads():
    """Get list of all threads"""
    return [
        {'id': thread_id, 'name': info['name']} 
        for thread_id, info in st.session_state.threads.items()
    ]

def process_uploaded_file(uploaded_file):
    """Handle file upload and vector store integration"""
    try:
        if uploaded_file is None:
            return False
            
        client = get_client()
        if not client:
            return False
        
        # Save file temporarily
        temp_path = os.path.join(UPLOAD_FOLDER, uploaded_file.name)
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        # Upload to vector store
        with open(temp_path, "rb") as f:
            file_batch = client.vector_stores.file_batches.upload_and_poll(
                vector_store_id='vs_6891e6eddc188191b3535499ce08396f',
                files=[f]
            )

        # Clean up
        os.remove(temp_path)
        
        if file_batch.status == "completed":
            return True
        return False

    except Exception as e:
        st.error(f"Error uploading file: {str(e)}")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False

def handle_tool_calls(tool_calls, thread_id, run_id):
    """Process tool calls from the assistant"""
    # Transform tool_calls into a list of objects
    print("Processing tool calls...")
    tool_calls_list = []
    for tool_call in tool_calls:
        print(f"Processing tool call: {tool_call.function.name} with arguments {tool_call.function.arguments}")
        tool_call_object = {
            tool_call.function.name: {
                "arguments": json.loads(tool_call.function.arguments)
            }
        }
        tool_calls_list.append(tool_call_object)
    
    tools_outputs = []
    
    # Process each tool call
    for tool_call in tool_calls:
        args = json.loads(tool_call.function.arguments)
        
        if tool_call.function.name == 'add_to_dashboard':
            result = add_to_dashboard(args['company_names'])
            tools_outputs.append({
                "tool_call_id": tool_call.id,
                "output": json.dumps(result)
            })
        elif tool_call.function.name == 'send_email_calendar_invite':
            result = send_email_calendar_invite(args['date'], args['event'])
            tools_outputs.append({
                "tool_call_id": tool_call.id,
                "output": json.dumps(result)
            })
    
    return tools_outputs

def add_to_dashboard(company_names):
    """Add companies to dashboard"""
    results = {}
    for company in company_names:
        try:
            # Create timestamp in ISO format for JSON serialization
            current_time = datetime.now(timezone.utc).isoformat()
            
            # Check if company exists in database
            response = supabase.table('tickers').select('ticker').eq('ticker', company).execute()
            
            if response.data:
                # Update existing company
                supabase.table('tickers').update(
                    {'last_accessed': current_time}
                ).eq('ticker', company).execute()
                results[company] = f"Updated last accessed time for {company}"
            else:
                # Add new company
                supabase.table('tickers').insert(
                    {'ticker': company, 'last_accessed': current_time}
                ).execute()
                results[company] = f"Added {company} to dashboard"
                
        except Exception as e:
            results[company] = f"Error processing {company}: {str(e)}"
    
    return results

def ask_question(question, thread_id):
    """Send question to assistant and get response"""
    try:
        if not question or not thread_id:
            return None
        if thread_id not in st.session_state.threads:
            return None

        client = get_client()
        if not client:
            return None

        thread = st.session_state.threads[thread_id]['thread']
        assistant = client.beta.assistants.retrieve("asst_XyZMGdTIIvPQGUzHzdBuvZvn")

        # Create message
        message = client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=question
        )

        # Run assistant
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread.id,
            assistant_id=assistant.id,
        )

        # Check if the assistant requires actions
        if run.status == 'requires_action':
            print("Assistant requires action, processing tool calls...")
            tool_calls = run.required_action.submit_tool_outputs.tool_calls
            
            # Process tool calls and get outputs
            tool_outputs = handle_tool_calls(tool_calls, thread.id, run.id)
            
            # Submit tool outputs back to assistant
            run = client.beta.threads.runs.submit_tool_outputs_and_poll(
                thread_id=thread.id,
                run_id=run.id,
                tool_outputs=tool_outputs
            )

        # Get final response
        messages = client.beta.threads.messages.list(
            thread_id=thread.id
        )
        
        return messages.data[0].content[0].text.value

    except Exception as e:
        st.error(f"Error processing question: {str(e)}")
        return None

def create_email_pdf(msg):
    """Convert an email to a PDF with all content and metadata repeated every 1500 characters"""
    try:
        import html2text
        from fpdf import FPDF
        import tempfile
        import re
        from PIL import Image
        import io
        import base64
        import unicodedata

        # Initialize PDF with standard font and larger margins
        pdf = FPDF()
        pdf.set_left_margin(15)
        pdf.set_right_margin(15)
        pdf.set_top_margin(15)
        pdf.add_page()
        pdf.set_font("Arial", size=9)  # Even smaller font
        
        # Create metadata header
        from_str = sanitize_text(str(msg.from_))
        to_str = sanitize_text(str(', '.join(msg.to) if isinstance(msg.to, list) else str(msg.to)))
        subject_str = sanitize_text(str(msg.subject))
        
        # Keep metadata short and simple
        metadata = f"""From: {from_str[:50]}...
To: {to_str[:50]}...
Subject: {subject_str[:50]}...
Date: {msg.date.strftime('%Y-%m-%d %H:%M:%S')}
{'='*50}"""
        
        # Process email content
        if msg.html:
            h2t = html2text.HTML2Text()
            h2t.ignore_links = True  # Ignore links to avoid long URLs
            h2t.body_width = 60  # Narrower width
            raw_text = h2t.handle(msg.html)
        else:
            raw_text = msg.text or "No content"
        
        # Sanitize content
        text_content = sanitize_text(raw_text)
        
        # Simple function to add text with basic wrapping
        def add_text_simple(pdf, text):
            """Add text with simple character-based wrapping"""
            # Split into lines
            lines = text.split('\n')
            
            for line in lines:
                # If line is empty, just add space
                if not line.strip():
                    pdf.ln(3)
                    continue
                
                # Break long lines into chunks of 60 characters
                while len(line) > 60:
                    chunk = line[:60]
                    # Try to break at a space if possible
                    if ' ' in chunk:
                        last_space = chunk.rfind(' ')
                        if last_space > 40:  # Only break at space if it's not too early
                            chunk = chunk[:last_space]
                            line = line[last_space+1:]
                        else:
                            line = line[60:]
                    else:
                        line = line[60:]
                    
                    try:
                        pdf.cell(0, 4, chunk, ln=True)
                    except:
                        # If even this fails, skip this chunk
                        pdf.cell(0, 4, "[Content skipped]", ln=True)
                
                # Add remaining text
                if line:
                    try:
                        pdf.cell(0, 4, line, ln=True)
                    except:
                        pdf.cell(0, 4, "[Content skipped]", ln=True)
        
        # Add initial metadata
        add_text_simple(pdf, metadata)
        pdf.ln(5)
        
        # Split content into chunks
        max_chunk_size = 1200  # Smaller chunks
        chunks = []
        for i in range(0, len(text_content), max_chunk_size):
            chunks.append(text_content[i:i+max_chunk_size])
        
        # Add content chunks
        for i, chunk in enumerate(chunks[:10]):  # Limit to 10 chunks to avoid huge PDFs
            try:
                add_text_simple(pdf, f"\n--- Part {i+1} ---\n")
                add_text_simple(pdf, chunk)
                pdf.ln(5)
                add_text_simple(pdf, metadata)
                pdf.ln(8)
                
                # Add new page if getting close to bottom
                if pdf.get_y() > 250:
                    pdf.add_page()
                    
            except Exception as chunk_error:
                # Skip problematic chunks
                add_text_simple(pdf, f"[Part {i+1} could not be processed]")
                continue
        
        # Save PDF
        pdf_path = tempfile.mktemp(suffix=".pdf")
        pdf.output(pdf_path)
        
        return pdf_path
        
    except Exception as e:
        st.error(f"Error creating PDF: {str(e)}")
        return None

def sync_from_email():
    """Fetch emails and attachments and add them to the vector store"""
    try:
        client = get_client()
        if not client:
            return False

        successful_uploads = 0
        with MailBox("imap.gmail.com").login(email, password, 'INBOX') as mailbox:
            for msg in mailbox.fetch(AND(seen=False)):
                try:
                    # Create a PDF from the email content
                    pdf_path = create_email_pdf(msg)
                    if pdf_path:
                        # Upload the PDF to the vector store
                        with open(pdf_path, "rb") as f:
                            file_batch = client.vector_stores.file_batches.upload_and_poll(
                                vector_store_id='vs_6891e6eddc188191b3535499ce08396f',
                                files=[f]
                            )
                        
                        # Clean up temporary PDF file
                        os.remove(pdf_path)
                        
                        if file_batch.status == "completed":
                            successful_uploads += 1
                    
                    # Process attachments separately
                    for att in msg.attachments:
                        if os.path.splitext(att.filename)[1].lower() in ['.pdf', '.txt', '.csv', '.docx']:
                            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(att.filename)[1]) as temp_att:
                                temp_att.write(att.payload)
                                temp_att_path = temp_att.name
                            
                            with open(temp_att_path, "rb") as f:
                                file_batch = client.vector_stores.file_batches.upload_and_poll(
                                    vector_store_id='vs_6891e6eddc188191b3535499ce08396f',
                                    files=[f]
                                )
                            
                            os.remove(temp_att_path)
                            
                            if file_batch.status == "completed":
                                successful_uploads += 1
                    
                except Exception as inner_e:
                    st.error(f"Error processing email: {str(inner_e)}")
                    continue

        return successful_uploads

    except Exception as e:
        st.error(f"Error syncing from email: {str(e)}")
        return False

def create_calendar_event(event_name, start_datetime, end_datetime=None, description=None):
    """Create a calendar event and return the file path"""
    C = Calendar()
    e = Event()
    e.name = event_name
    e.begin = start_datetime
    if end_datetime is None:
        end_datetime = start_datetime + timedelta(days=1)
    e.end = end_datetime
    if description:
        e.description = description
    C.events.add(e)

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ics') as f:
            f.write(C.serialize().encode('utf-8'))
            file_path = f.name
        return file_path
    except Exception as e:
        st.error(f"Error creating calendar event: {str(e)}")
        return None

def send_email_with_attachment(subject, body, attachment_path):
    """Send an email with an ICS attachment"""
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(email_sender, sender_password)

        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = email_sender
        msg['To'] = EMAIL_RECEIVER

        msg.attach(MIMEText(body))

        with open(attachment_path, 'rb') as f:
            attachment = MIMEApplication(f.read(), _subtype='ics')
            attachment.add_header('Content-Disposition', 'attachment', 
                                filename=os.path.basename(attachment_path))
            msg.attach(attachment)

        server.sendmail(email_sender, EMAIL_RECEIVER, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        st.error(f"Error sending email: {str(e)}")
        return False

def send_email_calendar_invite(date: str, eventname: str):
    """
    Create and send a calendar invite email.
    
    Args:
        date (str): ISO 8601 format date or 'unknown+X' where X is hours from now
        eventname (str): Name of the event
    
    Returns:
        dict: Status and message of the operation
    """
    try:
        # Handle unknown+ cases
        if date.startswith('unknown+'):
            try:
                # Extract hours to add from unknown+X format
                hours_to_add = int(date.split('+')[1])
                event_datetime = datetime.now(timezone.utc) + timedelta(hours=hours_to_add)
            except (IndexError, ValueError):
                return {
                    "status": "error",
                    "message": "Invalid unknown+ format. Expected unknown+X where X is hours to add"
                }
        else:
            # Handle ISO 8601 format
            try:
                event_datetime = datetime.fromisoformat(date.replace('Z', '+00:00'))
            except ValueError:
                return {
                    "status": "error",
                    "message": "Invalid date format. Expected ISO 8601 format or unknown+X format"
                }

        # Create the calendar event
        ics_path = create_calendar_event(
            event_name=eventname,
            start_datetime=event_datetime,
            description=f"Calendar invite for {eventname}"
        )
        
        if not ics_path:
            return {"status": "error", "message": "Failed to create calendar event"}
        
        # Send the email with the calendar invite
        email_sent = send_email_with_attachment(
            subject=f"Calendar Invite: {eventname}",
            body=f"Please find attached the calendar invite for {eventname} scheduled for {event_datetime.strftime('%Y-%m-%d %H:%M %Z')}",
            attachment_path=ics_path
        )
        
        # Clean up temporary file
        try:
            os.unlink(ics_path)
        except:
            pass
            
        if email_sent:
            return {
                "status": "success",
                "message": f"Calendar invite sent for {eventname} scheduled for {event_datetime.strftime('%Y-%m-%d %H:%M %Z')}"
            }
        else:
            return {"status": "error", "message": "Failed to send email"}
            
    except Exception as e:
        return {"status": "error", "message": f"Calendar invite error: {str(e)}"}

def sanitize_text(text):
    """Sanitize text to make it compatible with standard PDF fonts"""
    if not text:
        return ""
    
    # Replace common problematic characters
    replacements = {
        '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',  # Smart quotes
        '\u2013': '-', '\u2014': '--',  # En/em dashes
        '\u2026': '...', # Ellipsis
        '\u00a0': ' ',  # Non-breaking space
        '\u2028': ' ', '\u2029': ' ',  # Line/paragraph separators
    }
    
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    
    # Ensure we only have printable ASCII
    result = ""
    for char in text:
        if ord(char) < 128 and (char.isprintable() or char in '\n\r\t'):
            result += char
        else:
            # Replace unsupported characters with simple substitutes
            if char in '""''„‟«»‹›': result += '"'
            elif char in '—–': result += '-'
            elif char in '•∙⋅': result += '*'
            else: result += ' '  # Replace any other unsupported char with space
    
    return result

# Page UI
st.title("Legal Assistant")
st.caption("Chat with your legal documents using AI")

# Sidebar
with st.sidebar:
    st.header("Legal Document Settings")
    
    # Thread Management
    st.subheader("Thread Management")
    new_thread_name = st.text_input("New Thread Name (optional)")
    
    if st.button("Create New Thread"):
        thread_id, thread_name = create_thread(new_thread_name)
        if thread_id:
            st.session_state.current_thread_id = thread_id
            st.session_state.current_thread_name = thread_name
            st.success(f"Created thread: {thread_name}")
            st.session_state.messages = []

    # Display existing threads
    threads = get_threads()
    if threads:
        st.subheader("Select Thread")
        thread_options = {thread['name']: thread['id'] for thread in threads}
        selected_thread = st.selectbox(
            "Choose a thread",
            options=list(thread_options.keys()),
            key="thread_selector"
        )
        
        if selected_thread:
            st.session_state.current_thread_id = thread_options[selected_thread]
            st.session_state.current_thread_name = selected_thread

        if st.button("Delete Current Thread"):
            if st.session_state.current_thread_id:
                if delete_thread(st.session_state.current_thread_id):
                    st.success("Thread deleted")
                    st.rerun()

    # File Upload
    st.subheader("Legal Document Upload")
    uploaded_file = st.file_uploader("Upload Legal Document", type=['pdf'])
    if uploaded_file:
        if process_uploaded_file(uploaded_file):
            st.success("Legal document uploaded successfully!")
        else:
            st.error("Failed to upload legal document")

    # Email Sync
    st.subheader("Email Sync")
    if st.button("Sync from Email"):
        with st.spinner("Syncing emails and attachments..."):
            uploads = sync_from_email()
            if uploads:
                st.success(f"Successfully processed {uploads} items from email!")
            else:
                st.error("Nothing to process or an error occurred.")

# Main chat interface
if st.session_state.current_thread_id:
    st.write(f"Current Thread: {st.session_state.current_thread_name}")
    
    # Display message history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    # Chat input
    if prompt := st.chat_input("What would you like to know about your legal documents?"):
        # Show user message
        with st.chat_message("user"):
            st.write(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        # Get and show assistant response
        with st.spinner("Analyzing..."):
            if response := ask_question(prompt, st.session_state.current_thread_id):
                with st.chat_message("assistant"):
                    st.write(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
else:
    st.info("Please select or create a thread to start chatting about your legal documents.")
