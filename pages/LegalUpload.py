import streamlit as st
from openai import OpenAI
import os
from datetime import datetime, timezone, timedelta
import tempfile
import json
import re
from fpdf import FPDF
import PyPDF2

# Initialize session state for legal document metadata
if 'legal_metadata' not in st.session_state:
    st.session_state.legal_metadata = None

# Create upload directory
UPLOAD_FOLDER = os.path.join(os.getcwd(), "temp")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def get_client():
    """Get or create OpenAI client"""
    print("🔧 DEBUG: get_client() called")
    if 'openai_client' not in st.session_state:
        print("🔧 DEBUG: Creating new OpenAI client")
        try:
            st.session_state.openai_client = OpenAI(
                api_key=os.getenv('OPENAI_API_KEY'),
                max_retries=3,
                timeout=20.0
            )
            print("🔧 DEBUG: OpenAI client created successfully")
        except Exception as e:
            print(f"🔧 DEBUG: Error creating OpenAI client: {str(e)}")
            st.error(f"Error initializing OpenAI client: {str(e)}")
            return None
    else:
        print("🔧 DEBUG: Using existing OpenAI client")
    return st.session_state.openai_client

def collect_legal_document_metadata():
    """Collect metadata about the legal document before processing"""
    st.subheader("📋 Document Information")
    st.info("Please provide details about this legal document to enhance AI processing")
    
    with st.form("document_info_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            doc_type = st.selectbox(
                "Document Type *",
                ["Contract", "NDA", "Court Filing", "Correspondence", "Agreement", "Other"],
                help="Type of legal document"
            )
            
            parties = st.text_area(
                "Parties Involved *",
                placeholder="e.g., Party A, Party B, Third-Party C",
                help="Names of all parties in this document"
            )
        
        with col2:
            important_dates = st.text_area(
                "Important Dates",
                placeholder="e.g., Filing deadline: 2023-12-15, Effective date: 2023-11-01",
                help="Any key dates mentioned in the document (format: Description: YYYY-MM-DD)"
            )
            
            jurisdiction = st.text_input(
                "Jurisdiction",
                placeholder="e.g., California, Federal",
                help="Relevant legal jurisdiction"
            )
        
        document_summary = st.text_area(
            "Document Summary/Notes",
            placeholder="Brief description or notes about this document",
            height=100
        )
        
        submitted = st.form_submit_button("✅ Confirm Document Info")
        
        if submitted:
            if not doc_type or not parties:
                st.error("Document Type and Parties are required fields!")
                return None
            
            metadata = {
                "doc_type": doc_type,
                "parties": parties,
                "important_dates": important_dates,
                "jurisdiction": jurisdiction,
                "summary": document_summary,
                "upload_time": datetime.now().isoformat()
            }
            
            st.session_state.legal_metadata = metadata
            st.success("✅ Document information saved! You can now upload your file.")
            return metadata
    
    return None

def enhance_legal_document_with_metadata(file_path, metadata):
    """Add metadata to document content for better context in vector store"""
    print(f"🔧 DEBUG: enhance_legal_document_with_metadata() called with file: {file_path}")
    print(f"🔧 DEBUG: Metadata: {metadata}")
    
    try:
        # Create metadata header
        header = f"""
LEGAL DOCUMENT METADATA:
Document Type: {metadata['doc_type']}
Parties: {metadata['parties']}
Jurisdiction: {metadata['jurisdiction']}
Important Dates: {metadata['important_dates']}
Summary: {metadata['summary']}
Upload Time: {metadata['upload_time']}
{'='*60}
        """.strip()
        
        print(f"🔧 DEBUG: Created metadata header: {header[:100]}...")
        
        # Read original PDF content
        original_content = ""
        try:
            print(f"🔧 DEBUG: Attempting to read PDF from: {file_path}")
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                print(f"🔧 DEBUG: PDF has {len(pdf_reader.pages)} pages")
                for i, page in enumerate(pdf_reader.pages):
                    page_text = page.extract_text()
                    print(f"🔧 DEBUG: Page {i+1} extracted {len(page_text)} characters")
                    original_content += page_text + "\n"
            print(f"🔧 DEBUG: Total extracted content: {len(original_content)} characters")
        except Exception as e:
            print(f"🔧 DEBUG: PDF extraction failed: {str(e)}")
            st.warning(f"Could not extract text from PDF: {str(e)}")
            original_content = f"[Original document: {os.path.basename(file_path)} - text extraction failed]"
        
        # Create enhanced PDF with metadata
        print("🔧 DEBUG: Creating enhanced PDF with metadata")
        pdf = FPDF()
        pdf.set_left_margin(15)
        pdf.set_right_margin(15)
        pdf.set_top_margin(15)
        pdf.add_page()
        pdf.set_font("Arial", size=9)
        
        def add_text_simple(pdf, text):
            """Add text with simple character-based wrapping"""
            lines = text.split('\n')
            for line in lines:
                if not line.strip():
                    pdf.ln(3)
                    continue
                
                while len(line) > 60:
                    chunk = line[:60]
                    if ' ' in chunk:
                        last_space = chunk.rfind(' ')
                        if last_space > 40:
                            chunk = chunk[:last_space]
                            line = line[last_space+1:]
                        else:
                            line = line[60:]
                    else:
                        line = line[60:]
                    
                    try:
                        pdf.cell(0, 4, chunk, ln=True)
                    except:
                        pdf.cell(0, 4, "[Content skipped]", ln=True)
                
                if line:
                    try:
                        pdf.cell(0, 4, line, ln=True)
                    except:
                        pdf.cell(0, 4, "[Content skipped]", ln=True)
        
        # Add metadata header
        print("🔧 DEBUG: Adding initial metadata header to PDF")
        add_text_simple(pdf, header)
        pdf.ln(5)
        
        # Split content into chunks and add metadata between them
        max_chunk_size = 1000
        chunks = []
        for i in range(0, len(original_content), max_chunk_size):
            chunks.append(original_content[i:i+max_chunk_size])
        
        print(f"🔧 DEBUG: Split content into {len(chunks)} chunks")
        
        # Add content chunks with metadata
        for i, chunk in enumerate(chunks[:15]):  # Limit to 15 chunks
            print(f"🔧 DEBUG: Processing chunk {i+1}/{min(len(chunks), 15)}")
            try:
                add_text_simple(pdf, f"\n--- Document Part {i+1} ---\n")
                add_text_simple(pdf, chunk)
                pdf.ln(5)
                add_text_simple(pdf, header)  # Repeat metadata
                pdf.ln(8)
                
                if pdf.get_y() > 250:
                    pdf.add_page()
                    
            except Exception as chunk_error:
                print(f"🔧 DEBUG: Error processing chunk {i+1}: {chunk_error}")
                add_text_simple(pdf, f"[Part {i+1} could not be processed]")
                continue
        
        # Save enhanced PDF
        enhanced_path = tempfile.mktemp(suffix=".pdf")
        print(f"🔧 DEBUG: Saving enhanced PDF to: {enhanced_path}")
        pdf.output(enhanced_path)
        print(f"🔧 DEBUG: Enhanced PDF saved successfully")
        
        return enhanced_path
        
    except Exception as e:
        print(f"🔧 DEBUG: Error in enhance_legal_document_with_metadata: {str(e)}")
        st.error(f"Error enhancing document: {str(e)}")
        return file_path  # Return original if enhancement fails

def extract_legal_dates(dates_text):
    """Extract dates from metadata for calendar integration"""
    if not dates_text:
        return []
    
    dates = []
    # Pattern: Description: YYYY-MM-DD
    pattern = r'([^:]+):\s*(\d{4}-\d{2}-\d{2})'
    
    for match in re.finditer(pattern, dates_text):
        description = match.group(1).strip()
        date_str = match.group(2).strip()
        
        dates.append({
            "description": description,
            "date": date_str
        })
    
    return dates

def process_legal_document(uploaded_file, metadata):
    """Process uploaded legal document with metadata enhancement"""
    print(f"🔧 DEBUG: process_legal_document() called")
    print(f"🔧 DEBUG: File name: {uploaded_file.name if uploaded_file else 'None'}")
    print(f"🔧 DEBUG: File size: {uploaded_file.size if uploaded_file else 'None'} bytes")
    print(f"🔧 DEBUG: Metadata: {metadata}")
    
    try:
        if uploaded_file is None or metadata is None:
            print("🔧 DEBUG: Missing file or metadata, returning False")
            return False
            
        client = get_client()
        if not client:
            print("🔧 DEBUG: Failed to get OpenAI client, returning False")
            return False
        
        # Save original file temporarily
        temp_path = os.path.join(UPLOAD_FOLDER, uploaded_file.name)
        print(f"🔧 DEBUG: Saving original file to: {temp_path}")
        
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        print(f"🔧 DEBUG: Original file saved, size: {os.path.getsize(temp_path)} bytes")

        # Enhance document with metadata
        print("🔧 DEBUG: Calling enhance_legal_document_with_metadata")
        enhanced_path = enhance_legal_document_with_metadata(temp_path, metadata)
        print(f"🔧 DEBUG: Enhanced document path: {enhanced_path}")
        
        if enhanced_path and os.path.exists(enhanced_path):
            enhanced_size = os.path.getsize(enhanced_path)
            print(f"🔧 DEBUG: Enhanced file size: {enhanced_size} bytes")
        else:
            print("🔧 DEBUG: Enhanced file not found or invalid path")

        # Upload enhanced document to vector store
        print("🔧 DEBUG: Starting upload to vector store vs_6891e6eddc188191b3535499ce08396f")
        
        with open(enhanced_path, "rb") as f:
            print("🔧 DEBUG: Calling vector_stores.file_batches.upload_and_poll")
            file_batch = client.vector_stores.file_batches.upload_and_poll(
                vector_store_id='vs_6891e6eddc188191b3535499ce08396f',
                files=[f]
            )
        
        print(f"🔧 DEBUG: Upload completed with status: {file_batch.status}")
        print(f"🔧 DEBUG: File batch details: {file_batch}")

        # Clean up temporary files
        print("🔧 DEBUG: Cleaning up temporary files")
        os.remove(temp_path)
        if enhanced_path != temp_path:
            os.remove(enhanced_path)
        print("🔧 DEBUG: Cleanup completed")
        
        if file_batch.status == "completed":
            print("🔧 DEBUG: Upload successful, returning True")
            return True
        else:
            print(f"🔧 DEBUG: Upload failed with status: {file_batch.status}")
            return False

    except Exception as e:
        print(f"🔧 DEBUG: Exception in process_legal_document: {str(e)}")
        st.error(f"Error uploading legal document: {str(e)}")
        # Clean up on error
        if 'temp_path' in locals() and os.path.exists(temp_path):
            print("🔧 DEBUG: Cleaning up temp_path on error")
            os.remove(temp_path)
        if 'enhanced_path' in locals() and enhanced_path != temp_path and os.path.exists(enhanced_path):
            print("🔧 DEBUG: Cleaning up enhanced_path on error")
            os.remove(enhanced_path)
        return False

# Page UI
st.title("📁 Legal Document Upload")
st.caption("Upload legal documents with contextual information for better AI processing")

# Step 1: Collect metadata
if st.session_state.legal_metadata is None:
    st.markdown("### Step 1: Document Information")
    st.markdown("First, please provide some information about your legal document:")
    
    collect_legal_document_metadata()
    
else:
    # Display collected metadata
    st.markdown("### ✅ Document Information Collected")
    metadata = st.session_state.legal_metadata
    
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Document Type:** {metadata['doc_type']}")
        st.write(f"**Parties:** {metadata['parties']}")
    with col2:
        st.write(f"**Jurisdiction:** {metadata['jurisdiction']}")
        st.write(f"**Important Dates:** {metadata['important_dates']}")
    
    if metadata['summary']:
        st.write(f"**Summary:** {metadata['summary']}")
    
    # Button to edit metadata
    if st.button("✏️ Edit Document Information"):
        st.session_state.legal_metadata = None
        st.rerun()
    
    st.markdown("---")
    
    # Step 2: File upload
    st.markdown("### Step 2: Upload Document")
    uploaded_file = st.file_uploader(
        "Upload your legal document", 
        type=['pdf'],
        help="Upload the PDF file of your legal document"
    )
    
    if uploaded_file:
        st.write(f"**File:** {uploaded_file.name}")
        st.write(f"**Size:** {uploaded_file.size} bytes")
        
        if st.button("🚀 Process and Upload Document"):
            with st.spinner("Processing legal document with metadata..."):
                if process_legal_document(uploaded_file, metadata):
                    st.success("✅ Legal document uploaded successfully!")
                    
                    # Extract and display dates for calendar reminders
                    dates = extract_legal_dates(metadata['important_dates'])
                    if dates:
                        st.markdown("### 📅 Important Dates Detected")
                        st.info("These dates were extracted from your document. You can set calendar reminders for them in the Legal Assistant chat.")
                        for date_info in dates:
                            st.write(f"• **{date_info['description']}**: {date_info['date']}")
                    
                    # Reset for next upload
                    if st.button("📄 Upload Another Document"):
                        st.session_state.legal_metadata = None
                        st.rerun()
                        
                else:
                    st.error("❌ Failed to upload legal document. Please try again.")

# Instructions
with st.expander("ℹ️ How to use this page"):
    st.markdown("""
    **Step 1: Document Information**
    - Provide details about your legal document
    - Document Type and Parties are required
    - Format dates as: Description: YYYY-MM-DD (e.g., Filing deadline: 2023-12-15)
    
    **Step 2: Upload Document**
    - Upload your PDF file
    - The document will be enhanced with your metadata for better AI understanding
    - Important dates will be extracted for calendar reminders
    
    **After Upload:**
    - Go to the Legal Assistant chat page to discuss your documents
    - Ask the AI to create calendar reminders for important dates
    - The AI will have full context about your document metadata
    """)
