import streamlit as st
from openai import OpenAI
import os
from datetime import datetime
import time
import imaplib
import json
from imap_tools import MailBox, AND
import tempfile
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
            name = f"Thread {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
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
                vector_store_id='vs_qUspcB7VllWXM4z7aAEdIK9L',
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

  # """pressing this button will upload all emails to the vector store"""
    


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
        assistant = client.beta.assistants.retrieve("asst_Wk1Ue0iDYkhbdiXXDPPJsvAV")

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

        # Get response
        messages = client.beta.threads.messages.list(
            thread_id=thread.id
        )
        
        return messages.data[0].content[0].text.value

    except Exception as e:
        st.error(f"Error processing question: {str(e)}")
        return None

def sync_from_email():
    """Fetch emails and attachments and add them to the vector store"""
    try:
        client = get_client()
        if not client:
            return False

        successful_uploads = 0
        with MailBox("imap.gmail.com").login(email, password, 'INBOX') as mailbox:
            #unseen only
            for msg in mailbox.fetch(AND(seen=False)):
                try:
                    # Create a temporary markdown file for the email content
                    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.md') as temp_email:
                        md_content = f"""# Email from {msg.from_}
**Subject**: {msg.subject}  
**Received**: {msg.date.strftime('%Y-%m-%d %H:%M:%S')}  

{msg.text or msg.html or ""}
"""
                        temp_email.write(md_content)
                        temp_email.flush()

                    # Upload email content to vector store
                    with open(temp_email.name, "rb") as f:
                        file_batch = client.vector_stores.file_batches.upload_and_poll(
                            vector_store_id='vs_qUspcB7VllWXM4z7aAEdIK9L',
                            files=[f]
                        )
                        if file_batch.status == "completed":
                            successful_uploads += 1

                    # Clean up email temp file
                    os.unlink(temp_email.name)

                    # Process attachments
                    for att in msg.attachments:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(att.filename)[1]) as temp_att:
                            temp_att.write(att.payload)
                            temp_att.flush()

                        # Upload attachment to vector store
                        with open(temp_att.name, "rb") as f:
                            file_batch = client.vector_stores.file_batches.upload_and_poll(
                                vector_store_id='vs_qUspcB7VllWXM4z7aAEdIK9L',
                                files=[f]
                            )
                            if file_batch.status == "completed":
                                successful_uploads += 1

                        # Clean up attachment temp file
                        os.unlink(temp_att.name)

                except Exception as e:
                    st.warning(f"Error processing an email or its attachments: {str(e)}")
                    continue

        return successful_uploads

    except Exception as e:
        st.error(f"Error syncing from email: {str(e)}")
        return False

# Page UI
st.title("AceBot Chat")
st.caption("Chat with your documents using AI")

# Sidebar
with st.sidebar:
    st.header("Settings")
    
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
    st.subheader("File Upload")
    uploaded_file = st.file_uploader("Upload PDF Document", type=['pdf'])
    if uploaded_file:
        if process_uploaded_file(uploaded_file):
            st.success("File uploaded successfully!")
        else:
            st.error("Failed to upload file")

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
    if prompt := st.chat_input("What would you like to know?"):
        # Show user message
        with st.chat_message("user"):
            st.write(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        # Get and show assistant response
        with st.spinner("Thinking..."):
            if response := ask_question(prompt, st.session_state.current_thread_id):
                with st.chat_message("assistant"):
                    st.write(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
else:
    st.info("Please select or create a thread to start chatting.")