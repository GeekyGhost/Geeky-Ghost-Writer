"""Geeky Ghost Writer - An Ollama-based book generator with project management and advanced editing features"""
import os
import gradio as gr
import time
import requests
import json
import threading
import shutil
import re
import sqlite3
from contextlib import closing
from datetime import datetime
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("ghostwriter.log", encoding='utf-8'),  # Add encoding='utf-8' here
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('GeekyGhostWriter')

# Import export-related libraries (conditional imports to handle missing libraries gracefully)
export_capabilities = {
    "txt": True,
    "pdf": False,
    "epub": False,
    "docx": False,
    "markdown": True
}

try:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    export_capabilities["pdf"] = True
except ImportError:
    pass

try:
    import ebooklib
    from ebooklib import epub
    export_capabilities["epub"] = True
except ImportError:
    pass

try:
    from docx import Document
    export_capabilities["docx"] = True
except ImportError:
    pass

# Create the base output directories
os.makedirs("book_output", exist_ok=True)
os.makedirs("series_output", exist_ok=True)

# Global variables
current_outline = None
current_book_title = None
current_book_folder = None
current_book_id = None
current_series_id = None
generation_active = False
generation_thread = None
log_messages = []

current_book_data = {
    "id": None,
    "title": None,
    "folder": None,
    "created_at": None,
    "series_id": None,
    "world_building": {},
    "world_building_hierarchy": {},
    "characters": {},
    "character_relationships": [],
    "character_arcs": {},
    "style": "",
    "target_audience": {},
    "chapters": []
}

# Track generation progress with more detail
generation_progress = {
    "total_chapters": 0,
    "completed_chapters": 0,
    "current_chapter": 0,
    "start_time": None,
    "estimated_completion_time": None
}

# Ollama API configuration
OLLAMA_BASE_URL = "http://localhost:11434/api"
DEFAULT_CONTEXT_SIZE = 8192  # Increased from default 2048 for better performance with outlines

# Database initialization
def initialize_database():
    """Initialize SQLite database for project persistence"""
    try:
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Create tables for projects, chapters, characters, world-building
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS projects (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        creation_date TEXT NOT NULL,
                        last_modified TEXT NOT NULL,
                        style TEXT,
                        series_id TEXT,
                        folder_path TEXT NOT NULL
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS chapters (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        chapter_number INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        content TEXT,
                        outline TEXT,
                        status TEXT,
                        FOREIGN KEY (project_id) REFERENCES projects (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS characters (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        description TEXT,
                        FOREIGN KEY (project_id) REFERENCES projects (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS character_relationships (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        character1_id TEXT NOT NULL,
                        character2_id TEXT NOT NULL,
                        relationship_type TEXT NOT NULL,
                        description TEXT,
                        FOREIGN KEY (project_id) REFERENCES projects (id),
                        FOREIGN KEY (character1_id) REFERENCES characters (id),
                        FOREIGN KEY (character2_id) REFERENCES characters (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS character_arcs (
                        id TEXT PRIMARY KEY,
                        character_id TEXT NOT NULL,
                        arc_point INTEGER NOT NULL,
                        description TEXT,
                        FOREIGN KEY (character_id) REFERENCES characters (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS world_building (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        category TEXT NOT NULL,
                        subcategory TEXT,
                        name TEXT NOT NULL,
                        content TEXT,
                        FOREIGN KEY (project_id) REFERENCES projects (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS series (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT,
                        creation_date TEXT NOT NULL,
                        folder_path TEXT NOT NULL
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS series_books (
                        series_id TEXT NOT NULL,
                        book_id TEXT NOT NULL,
                        book_order INTEGER,
                        PRIMARY KEY (series_id, book_id),
                        FOREIGN KEY (series_id) REFERENCES series (id),
                        FOREIGN KEY (book_id) REFERENCES projects (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS target_audience (
                        project_id TEXT PRIMARY KEY,
                        age_min INTEGER,
                        age_max INTEGER,
                        reading_level TEXT,
                        FOREIGN KEY (project_id) REFERENCES projects (id)
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS audience_accommodations (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        accommodation_type TEXT NOT NULL,
                        description TEXT,
                        FOREIGN KEY (project_id) REFERENCES projects (id)
                    )
                ''')
                
                conn.commit()
        return True
    except Exception as e:
        logger.error(f"Database initialization error: {str(e)}")
        return False

def log_message(message):
    """Add a message to the log and return all messages"""
    log_messages.append(message)
    logger.info(message)
    return "\n".join(log_messages)

def check_ollama_running():
    """Check if Ollama is running by making a request to list models"""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/tags", timeout=5)
        return response.status_code == 200
    except Exception:
        return False

def get_ollama_models():
    """Get list of available Ollama models"""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/tags", timeout=5)
        if response.status_code == 200:
            models_data = response.json()
            model_names = []
            
            # Extract model names from the response
            for model in models_data.get("models", []):
                # Extract the base name without tags
                name = model["name"].split(":")[0]
                if name not in model_names:
                    model_names.append(name)
            
            return model_names if model_names else ["mistral", "llama2"]
        else:
            return ["mistral", "llama2"]  # Default models if request fails
    except Exception as e:
        logger.error(f"Error getting Ollama models: {e}")
        return ["mistral", "llama2"]  # Default models if request fails

def generate_text(model, prompt, num_ctx=DEFAULT_CONTEXT_SIZE, max_retries=3, timeout=60):
    """
    Generate text using Ollama API with retry logic and improved error handling
    
    Args:
        model: The Ollama model to use
        prompt: The prompt to send to the model
        num_ctx: Context window size
        max_retries: Maximum number of retries if request fails
        timeout: Request timeout in seconds
        
    Returns:
        Generated text or error message
    """
    for retry in range(max_retries):
        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"num_ctx": num_ctx}
            }
            
            logger.debug(f"Sending request to Ollama with {num_ctx} context window")
            response = requests.post(
                f"{OLLAMA_BASE_URL}/generate",
                json=payload,
                timeout=timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get("response", "")
            else:
                error_msg = f"Error {response.status_code}: {response.text}"
                logger.warning(f"Attempt {retry+1}/{max_retries}: {error_msg}")
                
                # If we're out of retries, return the error
                if retry == max_retries - 1:
                    return f"Error: {error_msg}"
                
                # Wait before retrying with backoff
                time.sleep(2 ** retry)
        except requests.exceptions.Timeout:
            logger.warning(f"Attempt {retry+1}/{max_retries}: Request timed out after {timeout} seconds")
            if retry == max_retries - 1:
                return f"Error: Request timed out after {timeout} seconds"
            time.sleep(2 ** retry)
        except Exception as e:
            logger.warning(f"Attempt {retry+1}/{max_retries}: Unexpected error: {str(e)}")
            if retry == max_retries - 1:
                return f"Error: {str(e)}"
            time.sleep(2 ** retry)
    
    return "Error: Failed to generate text after multiple attempts"

def generate_text_batch(model, prompts, num_ctx=DEFAULT_CONTEXT_SIZE, max_concurrent=3):
    """
    Generate text for multiple prompts concurrently using a thread pool
    
    Args:
        model: The Ollama model to use
        prompts: List of prompts to send to the model
        num_ctx: Context window size
        max_concurrent: Maximum number of concurrent requests
        
    Returns:
        List of generated texts
    """
    results = [None] * len(prompts)
    
    def process_prompt(args):
        idx, prompt = args
        result = generate_text(model, prompt, num_ctx)
        return idx, result
    
    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = [executor.submit(process_prompt, (i, prompt)) for i, prompt in enumerate(prompts)]
        
        for future in as_completed(futures):
            try:
                idx, result = future.result()
                results[idx] = result
            except Exception as e:
                logger.error(f"Error in batch processing: {str(e)}")
    
    return results

def sanitize_folder_name(title):
    """Convert title to a valid folder name with unique ID"""
    # Replace invalid characters with underscores
    sanitized = re.sub(r'[\\/*?:"<>|]', "_", title)
    # Replace spaces with underscores
    sanitized = sanitized.replace(" ", "_")
    # Ensure the name is not empty
    if not sanitized:
        sanitized = "untitled_book"
    # Add a UUID to ensure uniqueness
    unique_id = str(uuid.uuid4())[:8]
    return f"{sanitized}_{unique_id}"

def create_safe_dropdown(label, choices, default_index=0, allow_custom=True):
    """
    Create a dropdown with valid default values to avoid JS errors.
    
    Args:
        label: Label for the dropdown
        choices: List of choices
        default_index: Index of default choice, -1 for no default
        allow_custom: Whether to allow custom values
    
    Returns:
        A gradio Dropdown component with safe defaults
    """
    if not choices:
        choices = ["No options available"]
    
    # Set a valid default value - never use None with allow_custom_value=True
    if default_index >= 0 and default_index < len(choices):
        value = choices[default_index]
    else:
        # Use empty string instead of None for safety
        value = ""
        
    return gr.Dropdown(
        label=label,
        choices=choices,
        value=value,
        allow_custom_value=allow_custom
    )

def format_outline_for_display():
    """Format the current outline for display in the UI"""
    if not current_outline:
        return ""
    
    formatted_outline = "# Generated Book Outline\n\n"
    for chapter in current_outline:
        formatted_outline += f"## Chapter {chapter['chapter_number']}: {chapter['title']}\n"
        formatted_outline += f"{chapter['prompt']}\n\n"
    
    return formatted_outline

def scan_project_folders():
    """Scan book_output directory and return a list of valid projects with full paths"""
    projects = []
    try:
        for item in os.listdir("book_output"):
            item_path = os.path.join("book_output", item)
            if os.path.isdir(item_path):
                # Check if this has a valid metadata file
                metadata_path = os.path.join(item_path, "book_metadata.json")
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, "r", encoding="utf-8") as f:
                            metadata = json.load(f)
                            title = metadata.get("title", os.path.basename(item_path))
                            # Store title and full path directly
                            projects.append((title, item_path))
                    except:
                        # If we can't read metadata, just use folder name
                        projects.append((item, item_path))
                else:
                    # No metadata, use folder name
                    projects.append((item, item_path))
    except Exception as e:
        logger.error(f"Error scanning project folders: {e}")
    
    return projects

def create_book_project(title, style_input="", target_audience=None, series_id=None):
    """Create a new book project with the given title"""
    global current_book_title, current_book_folder, current_book_data, current_book_id, current_series_id
    
    try:
        # Generate a unique book ID
        book_id = str(uuid.uuid4())
        # Sanitize the title for folder name with added uniqueness
        folder_name = sanitize_folder_name(title)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        book_folder = os.path.join("book_output", f"{folder_name}_{timestamp}")
        
        # Create the folder
        os.makedirs(book_folder, exist_ok=True)
        
        # Update current book info
        current_book_title = title
        current_book_folder = book_folder
        current_book_id = book_id
        
        # Handle series_id if it's a tuple
        if isinstance(series_id, tuple) and len(series_id) > 1:
            current_series_id = series_id[1]  # Extract the ID part
        else:
            current_series_id = series_id
        
        # Ensure target_audience is a dictionary
        if target_audience is None or not isinstance(target_audience, dict):
            target_audience = {}
        
        # Initialize book data structure
        current_book_data = {
            "id": book_id,
            "title": title,
            "folder": book_folder,
            "created_at": timestamp,
            "series_id": current_series_id,
            "style": style_input,
            "target_audience": target_audience,
            "world_building": {},
            "world_building_hierarchy": {},
            "characters": {},
            "character_relationships": [],
            "character_arcs": {},
            "chapters": []
        }
        
        # Save book metadata
        save_book_metadata()
        
        # Store in database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "INSERT INTO projects (id, title, creation_date, last_modified, style, series_id, folder_path) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (book_id, title, timestamp, timestamp, style_input, series_id, book_folder)
                )
                
                # If part of a series, add to series_books table
                if series_id:
                    # Get the next book order in the series
                    cursor.execute("SELECT COUNT(*) FROM series_books WHERE series_id = ?", (series_id,))
                    book_order = cursor.fetchone()[0] + 1
                    
                    cursor.execute(
                        "INSERT INTO series_books (series_id, book_id, book_order) VALUES (?, ?, ?)",
                        (series_id, book_id, book_order)
                    )
                
                # Add target audience if provided
                if target_audience:
                    cursor.execute(
                        "INSERT INTO target_audience (project_id, age_min, age_max, reading_level) VALUES (?, ?, ?, ?)",
                        (book_id, target_audience.get("age_min"), target_audience.get("age_max"), target_audience.get("reading_level"))
                    )
                    
                    # Add accommodations if provided
                    if "accommodations" in target_audience:
                        for accom in target_audience["accommodations"]:
                            accom_id = str(uuid.uuid4())
                            cursor.execute(
                                "INSERT INTO audience_accommodations (id, project_id, accommodation_type, description) VALUES (?, ?, ?, ?)",
                                (accom_id, book_id, accom.get("type"), accom.get("description"))
                            )
                
                conn.commit()
        
        message = f"Created new book project: '{title}' in folder: {book_folder}"
        logger.info(message)
        return log_message(message)
    
    except Exception as e:
        error_msg = f"Error creating book project: {str(e)}"
        logger.error(error_msg)
        return log_message(error_msg)

def save_book_metadata():
    """Save book metadata to a JSON file"""
    if not current_book_folder:
        return False
    
    try:
        metadata_path = os.path.join(current_book_folder, "book_metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(current_book_data, f, indent=2)
        
        # Also update the last_modified date in the database
        if current_book_id:
            with closing(sqlite3.connect('book_projects.db')) as conn:
                with closing(conn.cursor()) as cursor:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    cursor.execute(
                        "UPDATE projects SET last_modified = ? WHERE id = ?",
                        (timestamp, current_book_id)
                    )
                    conn.commit()
        
        return True
    except Exception as e:
        logger.error(f"Error saving book metadata: {str(e)}")
        return False

def load_book_project(project_path_or_tuple):
    """Load an existing book project by path"""
    global current_book_title, current_book_folder, current_book_data, current_book_id, current_series_id, current_outline
    
    try:
        # Extract path from tuple if needed
        if isinstance(project_path_or_tuple, tuple):
            if len(project_path_or_tuple) > 1:
                project_path = project_path_or_tuple[1]  # Take the path part
            else:
                project_path = project_path_or_tuple[0]
        else:
            project_path = project_path_or_tuple
            
        # Check if this is a valid directory
        if not os.path.isdir(project_path):
            msg = f"Project path not found: {project_path}"
            logger.warning(msg)
            return log_message(msg)
        
        # Load metadata from file
        metadata_path = os.path.join(project_path, "book_metadata.json")
        if not os.path.exists(metadata_path):
            msg = f"No metadata found in: {project_path}"
            logger.warning(msg)
            return log_message(msg)
            
        # Read the metadata
        with open(metadata_path, "r", encoding="utf-8") as f:
            current_book_data = json.load(f)
        
        # Update current book info
        current_book_title = current_book_data.get("title", os.path.basename(project_path))
        current_book_folder = project_path
        current_book_id = current_book_data.get("id")
        if not current_book_id:
            # Generate an ID if none exists
            current_book_id = str(uuid.uuid4())
            current_book_data["id"] = current_book_id
            # Save the updated metadata with the new ID
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(current_book_data, f, indent=2)
                
        current_series_id = current_book_data.get("series_id")
        
        # Load outline if available
        if current_book_data.get("chapters"):
            current_outline = current_book_data.get("chapters")
        
        # Sync with database - update or insert
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Check if this ID already exists
                cursor.execute("SELECT id FROM projects WHERE id = ?", (current_book_id,))
                existing = cursor.fetchone()
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                created_at = current_book_data.get("created_at", timestamp)
                style = current_book_data.get("style", "")
                
                if existing:
                    # Update existing record
                    cursor.execute(
                        """
                        UPDATE projects SET 
                        title = ?, 
                        last_modified = ?,
                        folder_path = ?
                        WHERE id = ?
                        """,
                        (current_book_title, timestamp, project_path, current_book_id)
                    )
                else:
                    # Insert new record
                    cursor.execute(
                        """
                        INSERT INTO projects 
                        (id, title, creation_date, last_modified, style, series_id, folder_path) 
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (current_book_id, current_book_title, created_at, timestamp, 
                         style, current_series_id, project_path)
                    )
                
                conn.commit()
        
        msg = f"Loaded book project: '{current_book_title}' from {project_path}"
        logger.info(msg)
        return log_message(msg)
        
    except Exception as e:
        error_msg = f"Error loading book project: {str(e)}"
        logger.error(error_msg)
        return log_message(error_msg)

def get_existing_projects():
    """Get list of existing book projects primarily by scanning folders"""
    # Directly scan folders first - more reliable than database
    folder_projects = scan_project_folders()
    
    # Also check database as a fallback
    try:
        db_projects = []
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "SELECT id, title, folder_path FROM projects ORDER BY last_modified DESC"
                )
                for project_id, title, folder_path in cursor.fetchall():
                    # Only add if the folder actually exists
                    if os.path.exists(folder_path) and os.path.isdir(folder_path):
                        # Check if this path is already in our results
                        if not any(folder_path == path for _, path in folder_projects):
                            db_projects.append((title, folder_path))
        
        # Combine both lists, with folder_projects taking precedence
        return folder_projects + db_projects
    except Exception as e:
        logger.error(f"Database lookup failed, using folder scan only: {e}")
        return folder_projects

def create_series(series_name, description):
    """Create a new book series"""
    try:
        # Create a unique series ID
        series_id = str(uuid.uuid4())
        
        # Create a folder for the series
        folder_name = sanitize_folder_name(series_name)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        series_folder = os.path.join("series_output", f"{folder_name}_{timestamp}")
        
        # Create the folder
        os.makedirs(series_folder, exist_ok=True)
        
        # Initialize series data structure
        series_data = {
            "id": series_id,
            "name": series_name,
            "folder": series_folder,
            "created_at": timestamp,
            "description": description,
            "books": [],
            "shared_world_building": {},
            "shared_characters": {},
            "timeline": []
        }
        
        # Save series metadata
        metadata_path = os.path.join(series_folder, "series_metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(series_data, f, indent=2)
        
        # Store in database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "INSERT INTO series (id, name, description, creation_date, folder_path) VALUES (?, ?, ?, ?, ?)",
                    (series_id, series_name, description, timestamp, series_folder)
                )
                conn.commit()
        
        message = f"Created new book series: '{series_name}' in folder: {series_folder}"
        logger.info(message)
        return message, series_id
    
    except Exception as e:
        error_msg = f"Error creating series: {str(e)}"
        logger.error(error_msg)
        return error_msg, None

def get_existing_series():
    """Get list of existing book series from the database"""
    try:
        series_list = []
        
        # First check database
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "SELECT id, name FROM series ORDER BY creation_date DESC"
                )
                db_series = cursor.fetchall()
                
                for series_id, name in db_series:
                    series_list.append((name, series_id))
        
        # If database has no entries, fall back to file system
        if not series_list:
            for item in os.listdir("series_output"):
                item_path = os.path.join("series_output", item)
                if os.path.isdir(item_path):
                    metadata_path = os.path.join(item_path, "series_metadata.json")
                    if os.path.exists(metadata_path):
                        try:
                            with open(metadata_path, "r", encoding="utf-8") as f:
                                metadata = json.load(f)
                                name = metadata.get("name", "Untitled Series")
                                series_id = metadata.get("id", item_path)
                                series_list.append((name, series_id))
                        except:
                            series_list.append((item, item_path))
                    else:
                        series_list.append((item, item_path))
        
        return series_list
    except Exception as e:
        logger.error(f"Error getting existing series: {e}")
        return []

def add_book_to_series(series_id, book_id):
    """Add a book to a series"""
    try:
        # Get series information
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Get series info
                cursor.execute("SELECT name, folder_path FROM series WHERE id = ?", (series_id,))
                series_info = cursor.fetchone()
                
                if not series_info:
                    return f"Series with ID {series_id} not found."
                
                series_name, series_folder = series_info
                
                # Get book info
                cursor.execute("SELECT title FROM projects WHERE id = ?", (book_id,))
                book_info = cursor.fetchone()
                
                if not book_info:
                    return f"Book with ID {book_id} not found."
                
                book_title = book_info[0]
                
                # Get the next book order in the series
                cursor.execute("SELECT COUNT(*) FROM series_books WHERE series_id = ?", (series_id,))
                book_order = cursor.fetchone()[0] + 1
                
                # Add book to series
                cursor.execute(
                    "INSERT OR REPLACE INTO series_books (series_id, book_id, book_order) VALUES (?, ?, ?)",
                    (series_id, book_id, book_order)
                )
                
                # Update book to reference series
                cursor.execute(
                    "UPDATE projects SET series_id = ? WHERE id = ?",
                    (series_id, book_id)
                )
                
                conn.commit()
        
        # Also update the series metadata file
        series_metadata_path = os.path.join(series_folder, "series_metadata.json")
        if os.path.exists(series_metadata_path):
            with open(series_metadata_path, "r", encoding="utf-8") as f:
                series_data = json.load(f)
            
            if book_id not in series_data["books"]:
                series_data["books"].append(book_id)
            
            with open(series_metadata_path, "w", encoding="utf-8") as f:
                json.dump(series_data, f, indent=2)
        
        # If this is the current book, update its data
        if current_book_id == book_id:
            global current_book_data, current_series_id
            current_book_data["series_id"] = series_id
            current_series_id = series_id
            save_book_metadata()
        
        message = f"Added book '{book_title}' to series '{series_name}'"
        logger.info(message)
        return log_message(message)
    
    except Exception as e:
        error_msg = f"Error adding book to series: {str(e)}"
        logger.error(error_msg)
        return log_message(error_msg)

def build_outline_prompt(initial_prompt, chapter_range, style_input=""):
    """
    Build a comprehensive prompt for outline generation
    
    Args:
        initial_prompt: The base prompt for the book idea
        chapter_range: Tuple of (start_chapter, end_chapter)
        style_input: Optional style information
        
    Returns:
        A complete prompt with all context for the specified chapter range
    """
    start_chapter, end_chapter = chapter_range
    
    # Add style information if provided
    style_prompt = ""
    if style_input:
        style_prompt = f"\nThe writing style should be: {style_input}\n"
    
    # Add world building info if available
    world_building_prompt = ""
    if current_book_data.get("world_building"):
        world_building_prompt = "\nWorld building information:\n"
        for key, value in current_book_data["world_building"].items():
            world_building_prompt += f"- {key}: {value}\n"
    
    # Add hierarchical world building if available
    if current_book_data.get("world_building_hierarchy"):
        if not world_building_prompt:
            world_building_prompt = "\nWorld building information:\n"
        
        for category, subcategories in current_book_data["world_building_hierarchy"].items():
            world_building_prompt += f"- {category}:\n"
            for subcategory, elements in subcategories.items():
                world_building_prompt += f"  - {subcategory}:\n"
                for name, content in elements.items():
                    world_building_prompt += f"    - {name}: {content}\n"
    
    # Add character info if available
    character_prompt = ""
    if current_book_data.get("characters"):
        character_prompt = "\nCharacter information:\n"
        for name, info in current_book_data["characters"].items():
            character_prompt += f"- {name}: {info}\n"
    
    # Add character relationships if available
    if current_book_data.get("character_relationships"):
        if not character_prompt:
            character_prompt = "\nCharacter information:\n"
        
        character_prompt += "\nCharacter relationships:\n"
        for rel in current_book_data["character_relationships"]:
            character_prompt += f"- {rel['character1']} and {rel['character2']}: {rel['type']} - {rel['description']}\n"
    
    # Add character arcs if available
    if current_book_data.get("character_arcs"):
        if not character_prompt:
            character_prompt = "\nCharacter information:\n"
        
        character_prompt += "\nCharacter arcs:\n"
        for char, arc_points in current_book_data["character_arcs"].items():
            character_prompt += f"- {char}'s arc: {arc_points}\n"
    
    # Add target audience info if available
    target_audience_prompt = ""
    if current_book_data.get("target_audience"):
        audience = current_book_data["target_audience"]
        target_audience_prompt = "\nTarget Audience Specifications:\n"
        
        # Age range
        if "age_min" in audience and "age_max" in audience:
            target_audience_prompt += f"- Age Range: {audience['age_min']}-{audience['age_max']} years\n"
        
        # Reading level
        if "reading_level" in audience:
            target_audience_prompt += f"- Reading Level: {audience['reading_level']}\n"
        
        # Neurodivergent accommodations
        if "accommodations" in audience:
            target_audience_prompt += "- Accommodations:\n"
            for accom in audience["accommodations"]:
                target_audience_prompt += f"  - {accom['type']}: {accom['description']}\n"
        
        # Content guidelines
        if "content_guidelines" in audience:
            target_audience_prompt += "- Content Guidelines:\n"
            for guideline in audience["content_guidelines"]:
                target_audience_prompt += f"  - {guideline}\n"
    
    # Create the batch-specific prompt
    batch_prompt = f"""
    Generate a detailed outline for chapters {start_chapter} to {end_chapter} of a book titled "{current_book_title}" based on this premise:
    
    {initial_prompt}
    {style_prompt}
    {world_building_prompt}
    {character_prompt}
    {target_audience_prompt}
    
    For each chapter, provide the following information in this exact format:
    
    Chapter [Number]: [Title]
    Key Events:
    - [Event 1]
    - [Event 2]
    - [Event 3]
    Character Developments: [Brief description of character developments]
    Setting: [Brief description of the setting]
    Tone: [Brief description of the emotional tone]
    
    Make sure each chapter has a unique title and at least 3 key events.
    Start your response with "OUTLINE:" and end with "END OF OUTLINE"
    """
    
    return batch_prompt

def generate_outline(initial_prompt, num_chapters, model_name, style_input=""):
    """
    Generate a book outline in batches with improved reliability
    
    Enhancements:
    1. Uses parallel processing for improved performance
    2. Implements better error handling
    3. Uses optimal context window size
    4. Processes chapters in smaller batches to avoid context limits
    """
    global current_outline, current_book_data
    
    # Check if we have an active book project
    if not current_book_folder:
        msg = "No active book project. Please create or load a book project first."
        logger.warning(msg)
        return "", log_message(msg)
    
    log_message(f"Starting outline generation using {model_name} model...")
    log_message(f"Number of chapters: {num_chapters}")
    
    try:
        # Update style in book data if provided
        if style_input:
            current_book_data["style"] = style_input
        
        # Add book title to prompt if not already present
        focused_prompt = initial_prompt
        if current_book_title and current_book_title.lower() not in initial_prompt.lower():
            focused_prompt = f"A book about {current_book_title}: {initial_prompt}"
            log_message(f"Enhancing prompt with book title for focus: '{focused_prompt}'")
        
        # Process chapters in smaller batches to avoid context window limitations
        # A batch size of 5 chapters works well for most models
        batch_size = 5
        all_chapters = []
        
        # Calculate how many batches we need
        num_batches = (num_chapters + batch_size - 1) // batch_size  # Ceiling division
        
        # Create batch ranges
        batch_ranges = []
        for i in range(num_batches):
            start_chapter = i * batch_size + 1
            end_chapter = min((i + 1) * batch_size, num_chapters)
            batch_ranges.append((start_chapter, end_chapter))
        
        log_message(f"Processing {num_chapters} chapters in {num_batches} batches...")
        
        # Prepare prompts for all batches
        batch_prompts = [build_outline_prompt(focused_prompt, batch_range, style_input) 
                         for batch_range in batch_ranges]
        
        # Generate outlines for all batches with limited concurrency
        max_concurrent = 2  # Limit concurrent requests to avoid overloading Ollama
        batch_results = generate_text_batch(model_name, batch_prompts, 
                                           num_ctx=DEFAULT_CONTEXT_SIZE, 
                                           max_concurrent=max_concurrent)
        
        # Process each batch result
        for batch_idx, (batch_range, outline_text) in enumerate(zip(batch_ranges, batch_results)):
            start_chapter, end_chapter = batch_range
            log_message(f"Processing outline batch for chapters {start_chapter} to {end_chapter}...")
            
            # Check for errors
            if outline_text.startswith("Error:"):
                log_message(f"Error generating outline batch {batch_idx+1}: {outline_text}")
                continue
            
            # Process the batch outline
            batch_chapters = process_outline(outline_text, end_chapter - start_chapter + 1)
            
            # Adjust chapter numbers
            for i, chapter in enumerate(batch_chapters, start_chapter):
                chapter["chapter_number"] = i
            
            # Add to our collection
            all_chapters.extend(batch_chapters)
        
        # Check if we have any chapters
        if not all_chapters:
            log_message("Failed to generate any valid outline chapters.")
            return "", "Failed to generate outline. Please try again with different parameters."
        
        # If we have fewer chapters than requested, fill in with placeholders
        while len(all_chapters) < num_chapters:
            next_num = len(all_chapters) + 1
            all_chapters.append({
                "chapter_number": next_num,
                "title": f"Chapter {next_num}",
                "prompt": "- Key Events:\n- Event 1\n- Event 2\n- Event 3\n- Character Developments: Character development continues\n- Setting: Setting for this chapter\n- Tone: Tone for this chapter"
            })
        
        # Ensure proper chapter numbering and sort by chapter number
        for i, chapter in enumerate(all_chapters, 1):
            chapter["chapter_number"] = i
        
        # Sort chapters by chapter number
        all_chapters.sort(key=lambda x: x["chapter_number"])
        
        # Set the complete outline
        current_outline = all_chapters
        current_book_data["chapters"] = all_chapters
        save_book_metadata()
        
        # Format the outline for display
        formatted_outline = "# Generated Book Outline\n\n"
        for chapter in all_chapters:
            formatted_outline += f"## Chapter {chapter['chapter_number']}: {chapter['title']}\n"
            formatted_outline += f"{chapter['prompt']}\n\n"
        
        # Save the outline to file
        outline_path = os.path.join(current_book_folder, "outline.txt")
        with open(outline_path, "w", encoding="utf-8") as f:
            for chapter in all_chapters:
                f.write(f"\nChapter {chapter['chapter_number']}: {chapter['title']}\n")
                f.write("-" * 50 + "\n")
                f.write(chapter['prompt'] + "\n")
        
        # Save to database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                for chapter in all_chapters:
                    # Generate unique ID for the chapter
                    chapter_id = str(uuid.uuid4())
                    
                    # Check if chapter already exists for this project with this number
                    cursor.execute(
                        "SELECT id FROM chapters WHERE project_id = ? AND chapter_number = ?",
                        (current_book_id, chapter['chapter_number'])
                    )
                    existing_chapter = cursor.fetchone()
                    
                    if existing_chapter:
                        # Update existing chapter
                        cursor.execute(
                            "UPDATE chapters SET title = ?, outline = ?, status = ? WHERE id = ?",
                            (chapter['title'], chapter['prompt'], "outlined", existing_chapter[0])
                        )
                    else:
                        # Insert new chapter
                        cursor.execute(
                            "INSERT INTO chapters (id, project_id, chapter_number, title, outline, status) VALUES (?, ?, ?, ?, ?, ?)",
                            (chapter_id, current_book_id, chapter['chapter_number'], chapter['title'], chapter['prompt'], "outlined")
                        )
                
                conn.commit()
        
        msg = f"v Outline generation complete! Saved to {outline_path}"
        logger.info(msg)
        return formatted_outline, log_message(msg)
    
    except Exception as e:
        error_msg = f"Error generating outline: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return "", log_message(error_msg)

def process_outline(outline_text, num_chapters):
    """
    Process outline text into structured chapters with improved error handling
    
    Args:
        outline_text: Text output from the LLM containing the outline
        num_chapters: Expected number of chapters
        
    Returns:
        List of chapter dictionaries with structured information
    """
    import re
    
    # Extract the outline content between markers
    outline_content = outline_text
    if "OUTLINE:" in outline_text:
        start_idx = outline_text.find("OUTLINE:")
        end_idx = outline_text.find("END OF OUTLINE")
        if end_idx == -1:
            end_idx = len(outline_text)
        outline_content = outline_text[start_idx:end_idx].strip()
    
    # Split by chapter headers
    # Regular expression to match "Chapter X: Title" pattern
    chapter_pattern = re.compile(r'Chapter\s+(\d+)\s*:\s*(.*?)(?=\n|$)', re.IGNORECASE)
    
    # Find all chapter headers with chapter numbers and titles
    chapter_matches = list(chapter_pattern.finditer(outline_content))
    
    # If no chapter headers found, try alternative split method
    if not chapter_matches:
        logger.warning("No properly formatted chapter headers found. Attempting alternative parsing.")
        return process_outline_alternative(outline_content, num_chapters)
    
    chapters = []
    
    # Process each chapter
    for i in range(len(chapter_matches)):
        try:
            current_match = chapter_matches[i]
            chapter_num = int(current_match.group(1))
            chapter_title = current_match.group(2).strip()
            
            # Find the content for this chapter
            start_pos = current_match.end()
            end_pos = len(outline_content)
            if i < len(chapter_matches) - 1:
                end_pos = chapter_matches[i + 1].start()
            
            chapter_content = outline_content[start_pos:end_pos].strip()
            
            # Extract key sections using patterns
            events_match = re.search(r'Key Events:(.*?)(?=Character Developments:|Setting:|Tone:|$)', 
                                  chapter_content, re.DOTALL | re.IGNORECASE)
            character_match = re.search(r'Character Developments:(.*?)(?=Setting:|Tone:|$)', 
                                     chapter_content, re.DOTALL | re.IGNORECASE)
            setting_match = re.search(r'Setting:(.*?)(?=Tone:|$)', 
                                   chapter_content, re.DOTALL | re.IGNORECASE)
            tone_match = re.search(r'Tone:(.*?)(?=$)', 
                                chapter_content, re.DOTALL | re.IGNORECASE)
            
            # Extract content for each section or use placeholders
            events = events_match.group(1).strip() if events_match else "- Event 1\n- Event 2\n- Event 3"
            character = character_match.group(1).strip() if character_match else "Character development continues"
            setting = setting_match.group(1).strip() if setting_match else "Setting for this chapter"
            tone = tone_match.group(1).strip() if tone_match else "Tone for this chapter"
            
            # Format chapter info
            chapter_info = {
                "chapter_number": chapter_num,
                "title": chapter_title,
                "prompt": "\n".join([
                    f"Key Events: {events}",
                    f"Character Developments: {character}",
                    f"Setting: {setting}",
                    f"Tone: {tone}"
                ])
            }
            
            chapters.append(chapter_info)
            
        except Exception as e:
            logger.error(f"Error processing Chapter {i+1}: {str(e)}")
            # Add a minimal placeholder chapter
            chapters.append({
                "chapter_number": i+1,
                "title": f"Chapter {i+1}",
                "prompt": "Key Events:\n- Event 1\n- Event 2\n- Event 3\nCharacter Developments: Character development continues\nSetting: Setting for this chapter\nTone: Tone for this chapter"
            })
    
    # Ensure we have the requested number of chapters
    while len(chapters) < num_chapters:
        next_num = len(chapters) + 1
        chapters.append({
            "chapter_number": next_num,
            "title": f"Chapter {next_num}",
            "prompt": "Key Events:\n- Event 1\n- Event 2\n- Event 3\nCharacter Developments: Character development continues\nSetting: Setting for this chapter\nTone: Tone for this chapter"
        })
    
    # Trim extra chapters
    if len(chapters) > num_chapters:
        chapters = chapters[:num_chapters]
    
    # Ensure proper chapter numbering
    for i, chapter in enumerate(chapters, 1):
        chapter["chapter_number"] = i
    
    return chapters

def process_outline_alternative(outline_content, num_chapters):
    """
    Alternative method to process outline text when regular parsing fails
    
    Args:
        outline_content: Text output from the LLM containing the outline
        num_chapters: Expected number of chapters
        
    Returns:
        List of chapter dictionaries with structured information
    """
    # Split content by lines
    lines = outline_content.split('\n')
    
    chapters = []
    current_chapter = None
    current_section = None
    
    # Simplified parsing logic
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Try to identify a chapter header
        if line.lower().startswith("chapter") or re.match(r'^\d+\.\s+', line):
            # Save previous chapter if exists
            if current_chapter:
                chapters.append(current_chapter)
            
            # Extract title
            title = line
            if ':' in line:
                title = line.split(':', 1)[1].strip()
            
            # Create new chapter
            current_chapter = {
                "chapter_number": len(chapters) + 1,
                "title": title,
                "sections": {
                    "Key Events": [],
                    "Character Developments": "",
                    "Setting": "",
                    "Tone": ""
                }
            }
            current_section = None
            
        elif current_chapter:
            # Try to identify section headers
            lower_line = line.lower()
            if "key events" in lower_line or "events" in lower_line:
                current_section = "Key Events"
            elif "character" in lower_line and "develop" in lower_line:
                current_section = "Character Developments"
            elif "setting" in lower_line:
                current_section = "Setting"
            elif "tone" in lower_line:
                current_section = "Tone"
            elif current_section:
                # Add content to current section
                if current_section == "Key Events" and line.startswith("-"):
                    current_chapter["sections"][current_section].append(line)
                elif current_section == "Key Events" and current_chapter["sections"][current_section]:
                    # Append to last event if not starting with bullet
                    current_chapter["sections"][current_section][-1] += " " + line
                else:
                    current_chapter["sections"][current_section] = line
    
    # Add the last chapter
    if current_chapter:
        chapters.append(current_chapter)
    
    # Convert to standardized format
    standardized_chapters = []
    for i, chapter in enumerate(chapters, 1):
        # Format events
        events = "\n".join(chapter["sections"]["Key Events"]) if chapter["sections"]["Key Events"] else "- Event 1\n- Event 2\n- Event 3"
        
        # Format other sections
        character = chapter["sections"]["Character Developments"] or "Character development continues"
        setting = chapter["sections"]["Setting"] or "Setting for this chapter"
        tone = chapter["sections"]["Tone"] or "Tone for this chapter"
        
        standardized_chapters.append({
            "chapter_number": i,
            "title": chapter["title"],
            "prompt": "\n".join([
                f"Key Events: {events}",
                f"Character Developments: {character}",
                f"Setting: {setting}",
                f"Tone: {tone}"
            ])
        })
    
    # Ensure we have the requested number of chapters
    while len(standardized_chapters) < num_chapters:
        next_num = len(standardized_chapters) + 1
        standardized_chapters.append({
            "chapter_number": next_num,
            "title": f"Chapter {next_num}",
            "prompt": "Key Events:\n- Event 1\n- Event 2\n- Event 3\nCharacter Developments: Character development continues\nSetting: Setting for this chapter\nTone: Tone for this chapter"
        })
    
    # Trim extra chapters
    if len(standardized_chapters) > num_chapters:
        standardized_chapters = standardized_chapters[:num_chapters]
    
    # Ensure proper chapter numbering
    for i, chapter in enumerate(standardized_chapters, 1):
        chapter["chapter_number"] = i
    
    return standardized_chapters

def revise_chapter_outline(chapter_number, revision_prompt, model_name):
    """Revise a specific chapter outline based on user feedback"""
    global current_outline, current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            logger.warning(msg)
            return "", log_message(msg)
        
        if not current_outline:
            msg = "No outline available. Please generate an outline first."
            logger.warning(msg)
            return "", log_message(msg)
        
        # Find the chapter to revise
        chapter_to_revise = None
        for chapter in current_outline:
            if chapter["chapter_number"] == chapter_number:
                chapter_to_revise = chapter
                break
        
        if not chapter_to_revise:
            msg = f"Chapter {chapter_number} not found in the outline."
            logger.warning(msg)
            return "", log_message(msg)
        
        # Create the revision prompt
        revision_prompt_full = f"""
        Revise the following chapter outline based on this feedback: "{revision_prompt}"
        
        Current outline for Chapter {chapter_number}: {chapter_to_revise['title']}
        {chapter_to_revise['prompt']}
        
        Provide a revised outline in the following format:
        
        Chapter {chapter_number}: [New Title if needed, or keep the existing title]
        Key Events:
        - [Event 1]
        - [Event 2]
        - [Event 3]
        Character Developments: [Brief description of character developments]
        Setting: [Brief description of the setting]
        Tone: [Brief description of the emotional tone]
        
        Start your response with "REVISED OUTLINE:" and end with "END OF REVISION"
        """
        
        # Generate the revised outline with increased context window
        revised_text = generate_text(model_name, revision_prompt_full, num_ctx=DEFAULT_CONTEXT_SIZE)
        
        # Check for errors
        if revised_text.startswith("Error:"):
            logger.error(f"Error revising chapter: {revised_text}")
            return "", log_message(f"Error revising chapter: {revised_text}")
        
        # Extract the revised outline
        if "REVISED OUTLINE:" in revised_text:
            start_idx = revised_text.find("REVISED OUTLINE:")
            end_idx = revised_text.find("END OF REVISION")
            if end_idx == -1:
                end_idx = len(revised_text)
            revised_content = revised_text[start_idx:end_idx].strip()
        else:
            revised_content = revised_text
        
        # Extract just the content after "REVISED OUTLINE:" if present
        if "REVISED OUTLINE:" in revised_content:
            revised_content = revised_content.split("REVISED OUTLINE:")[1].strip()
        
        # Parse the revised chapter
        chapter_line = ""
        for line in revised_content.split('\n'):
            if line.startswith(f"Chapter {chapter_number}:"):
                chapter_line = line
                break
        
        if chapter_line:
            title = chapter_line.replace(f"Chapter {chapter_number}:", "").strip()
        else:
            title = chapter_to_revise['title']  # Keep existing title
        
        # Update the chapter
        chapter_to_revise['title'] = title
        chapter_to_revise['prompt'] = revised_content.replace(chapter_line, "").strip()
        
        # Update in the database
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "UPDATE chapters SET title = ?, outline = ? WHERE project_id = ? AND chapter_number = ?",
                    (title, chapter_to_revise['prompt'], current_book_id, chapter_number)
                )
                conn.commit()
        
        # Save the updated metadata
        save_book_metadata()
        
        # Update the outline file
        outline_path = os.path.join(current_book_folder, "outline.txt")
        with open(outline_path, "w") as f:
            for chapter in current_outline:
                f.write(f"\nChapter {chapter['chapter_number']}: {chapter['title']}\n")
                f.write("-" * 50 + "\n")
                f.write(chapter['prompt'] + "\n")
        
        # Format the outline for display
        formatted_outline = "# Generated Book Outline\n\n"
        for chapter in current_outline:
            formatted_outline += f"## Chapter {chapter['chapter_number']}: {chapter['title']}\n"
            formatted_outline += f"{chapter['prompt']}\n\n"
        
        msg = f"v Chapter {chapter_number} outline revised successfully!"
        logger.info(msg)
        return formatted_outline, log_message(msg)
    
    except Exception as e:
        error_msg = f"Error revising chapter outline: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return "", log_message(error_msg)

def generate_chapter(chapter_number, chapter_info, model_name):
    """Generate a single chapter using Ollama with increased context window and better error handling"""
    try:
        # Check if we have an active book project
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            logger.warning(msg)
            return log_message(msg)
        
        # Create the prompt for the chapter
        style_prompt = ""
        if current_book_data.get("style"):
            style_prompt = f"\nThe writing style should be: {current_book_data['style']}\n"
        
        # Add world building info if available
        world_building_prompt = ""
        if current_book_data.get("world_building"):
            world_building_prompt = "\nWorld building information:\n"
            for key, value in current_book_data["world_building"].items():
                world_building_prompt += f"- {key}: {value}\n"
        
        # Add hierarchical world building if available
        if current_book_data.get("world_building_hierarchy"):
            if not world_building_prompt:
                world_building_prompt = "\nWorld building information:\n"
            
            for category, subcategories in current_book_data["world_building_hierarchy"].items():
                world_building_prompt += f"- {category}:\n"
                for subcategory, elements in subcategories.items():
                    world_building_prompt += f"  - {subcategory}:\n"
                    for name, content in elements.items():
                        world_building_prompt += f"    - {name}: {content}\n"
        
        # Add character info if available
        character_prompt = ""
        if current_book_data.get("characters"):
            character_prompt = "\nCharacter information:\n"
            for name, info in current_book_data["characters"].items():
                character_prompt += f"- {name}: {info}\n"
        
        # Add character relationships if available
        if current_book_data.get("character_relationships"):
            if not character_prompt:
                character_prompt = "\nCharacter information:\n"
            
            character_prompt += "\nCharacter relationships:\n"
            for rel in current_book_data["character_relationships"]:
                character_prompt += f"- {rel['character1']} and {rel['character2']}: {rel['type']} - {rel['description']}\n"
        
        # Add character arcs if available
        if current_book_data.get("character_arcs"):
            if not character_prompt:
                character_prompt = "\nCharacter information:\n"
            
            character_prompt += "\nCharacter arcs:\n"
            for char, arc_points in current_book_data["character_arcs"].items():
                character_prompt += f"- {char}'s arc: {arc_points}\n"
        
        # Add target audience info if available
        target_audience_prompt = ""
        if current_book_data.get("target_audience"):
            audience = current_book_data["target_audience"]
            target_audience_prompt = "\nTarget Audience Specifications:\n"
            
            # Age range
            if "age_min" in audience and "age_max" in audience:
                target_audience_prompt += f"- Age Range: {audience['age_min']}-{audience['age_max']} years\n"
            
            # Reading level
            if "reading_level" in audience:
                target_audience_prompt += f"- Reading Level: {audience['reading_level']}\n"
            
            # Neurodivergent accommodations
            if "accommodations" in audience:
                target_audience_prompt += "- Accommodations:\n"
                for accom in audience["accommodations"]:
                    target_audience_prompt += f"  - {accom['type']}: {accom['description']}\n"
            
            # Content guidelines
            if "content_guidelines" in audience:
                target_audience_prompt += "- Content Guidelines:\n"
                for guideline in audience["content_guidelines"]:
                    target_audience_prompt += f"  - {guideline}\n"
        
        chapter_prompt = f"""
        You are writing Chapter {chapter_number}: {chapter_info['title']} of a book titled "{current_book_title}".
        
        Follow these guidelines for the chapter:
        {chapter_info['prompt']}
        {style_prompt}
        {world_building_prompt}
        {character_prompt}
        {target_audience_prompt}
        
        Write a complete, engaging chapter that follows these guidelines. The chapter should be at 
        least 2000 words. Include dialogue, description, and character development.
        
        Make sure to:
        1. Follow the key events listed
        2. Develop the characters as specified
        3. Use the specified setting
        4. Maintain the specified emotional tone
        5. Write a complete chapter with a beginning, middle, and end
        
        Do not include a chapter heading or the word "Chapter" in your response.
        Just write the prose of the chapter.
        """
        
        # Generate the chapter with a larger context window
        logger.info(f"Generating Chapter {chapter_number}: {chapter_info['title']}...")
        chapter_content = generate_text(model_name, chapter_prompt, num_ctx=DEFAULT_CONTEXT_SIZE, timeout=120)
        
        # Check for errors
        if chapter_content.startswith("Error:"):
            logger.error(f"Error generating Chapter {chapter_number}: {chapter_content}")
            return log_message(f"Error generating Chapter {chapter_number}: {chapter_content}")
        
        # Save the chapter
        save_path = os.path.join(current_book_folder, f"chapter_{chapter_number:02d}.txt")
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(f"Chapter {chapter_number}: {chapter_info['title']}\n\n")
            f.write(chapter_content)
        
        # Update chapter in database
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Check if chapter already exists
                cursor.execute(
                    "SELECT id FROM chapters WHERE project_id = ? AND chapter_number = ?",
                    (current_book_id, chapter_number)
                )
                existing_chapter = cursor.fetchone()
                
                if existing_chapter:
                    # Update existing chapter
                    cursor.execute(
                        "UPDATE chapters SET content = ?, status = ? WHERE id = ?",
                        (chapter_content, "completed", existing_chapter[0])
                    )
                else:
                    # Insert new chapter
                    chapter_id = str(uuid.uuid4())
                    cursor.execute(
                        "INSERT INTO chapters (id, project_id, chapter_number, title, content, outline, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (chapter_id, current_book_id, chapter_number, chapter_info['title'], chapter_content, chapter_info['prompt'], "completed")
                    )
                
                conn.commit()
        
        logger.info(f"Chapter {chapter_number} generated and saved to {save_path}")
        return f"v Chapter {chapter_number} written and saved to {save_path}"
    
    except Exception as e:
        error_msg = f"Error generating Chapter {chapter_number}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return log_message(error_msg)

def calculate_estimated_completion_time():
    """Calculate estimated time to complete book generation"""
    global generation_progress
    
    if generation_progress["completed_chapters"] == 0:
        return "Calculating..."
    
    # Calculate elapsed time and average time per chapter
    elapsed_time = time.time() - generation_progress["start_time"]
    avg_time_per_chapter = elapsed_time / generation_progress["completed_chapters"]
    
    # Calculate remaining time
    remaining_chapters = generation_progress["total_chapters"] - generation_progress["completed_chapters"]
    remaining_time = remaining_chapters * avg_time_per_chapter
    
    # Format remaining time
    if remaining_time < 60:
        return f"About {int(remaining_time)} seconds remaining"
    elif remaining_time < 3600:
        return f"About {int(remaining_time / 60)} minutes remaining"
    else:
        hours = int(remaining_time / 3600)
        mins = int((remaining_time % 3600) / 60)
        return f"About {hours} hours and {mins} minutes remaining"

def update_progress_info():
    """Update generation progress information"""
    global generation_progress
    
    # Calculate percentage complete
    if generation_progress["total_chapters"] > 0:
        percentage = (generation_progress["completed_chapters"] / generation_progress["total_chapters"]) * 100
    else:
        percentage = 0
    
    # Calculate estimated completion time
    time_remaining = calculate_estimated_completion_time()
    
    # Format the progress information
    progress_info = f"""## Generation Progress
- Chapters: {generation_progress["completed_chapters"]}/{generation_progress["total_chapters"]} ({percentage:.1f}%)
- Current chapter: {generation_progress["current_chapter"]}
- {time_remaining}
"""
    return progress_info

def generate_book_thread(model_name, progress=gr.Progress()):
    """Thread function for book generation with improved concurrency"""
    global current_outline, generation_active, generation_progress
    
    try:
        # Check if we have an active book project
        if not current_book_folder:
            log_message("No active book project. Please create or load a book project first.")
            generation_active = False
            return
        
        # Check if we have an outline
        if not current_outline:
            log_message("No outline available. Please generate an outline first.")
            generation_active = False
            return
        
        # Sort chapters by number
        sorted_outline = sorted(current_outline, key=lambda x: x["chapter_number"])
        
        # Initialize progress tracking
        generation_progress["total_chapters"] = len(sorted_outline)
        generation_progress["completed_chapters"] = 0
        generation_progress["current_chapter"] = 0
        generation_progress["start_time"] = time.time()
        
        # Generate each chapter
        progress(0, desc="Starting book generation")
        
        for i, chapter in enumerate(sorted_outline):
            if not generation_active:
                log_message("Book generation canceled.")
                break
                
            chapter_number = chapter["chapter_number"]
            progress_value = i / generation_progress["total_chapters"]
            
            # Update progress information
            generation_progress["current_chapter"] = chapter_number
            time_est = calculate_estimated_completion_time()
            progress_desc = f"Generating Chapter {chapter_number} - {time_est}"
            
            # Update progress display
            progress(progress_value, desc=progress_desc)
            log_message(f"Generating Chapter {chapter_number}: {chapter['title']}...")
            log_message(update_progress_info())
            
            # Generate the chapter
            result = generate_chapter(chapter_number, chapter, model_name)
            log_message(result)
            
            # Update progress counters
            generation_progress["completed_chapters"] += 1
            
            # Auto-save metadata after each chapter
            save_book_metadata()
            
            # Allow a short pause between chapters
            time.sleep(1)
        
        progress(1.0, desc="Book generation complete")
        log_message("v Book generation complete!")
        
    except Exception as e:
        error_msg = f"Error generating book: {str(e)}"
        logger.error(error_msg, exc_info=True)
        log_message(error_msg)
    
    finally:
        generation_active = False

def generate_selected_chapters(chapter_numbers, model_name, progress=gr.Progress()):
    """Generate only selected chapters with improved concurrency"""
    global current_outline, generation_active, generation_progress
    
    try:
        # Check if we have an active book project
        if not current_book_folder:
            log_message("No active book project. Please create or load a book project first.")
            generation_active = False
            return
        
        # Check if we have an outline
        if not current_outline:
            log_message("No outline available. Please generate an outline first.")
            generation_active = False
            return
        
        # Filter the outline to only include selected chapters
        selected_chapters = [ch for ch in current_outline if ch["chapter_number"] in chapter_numbers]
        
        if not selected_chapters:
            log_message("No valid chapters selected for generation.")
            generation_active = False
            return
        
        # Initialize progress tracking
        generation_progress["total_chapters"] = len(selected_chapters)
        generation_progress["completed_chapters"] = 0
        generation_progress["current_chapter"] = 0
        generation_progress["start_time"] = time.time()
        
        # Generate each selected chapter
        progress(0, desc="Starting selected chapter generation")
        
        for i, chapter in enumerate(selected_chapters):
            if not generation_active:
                log_message("Chapter generation canceled.")
                break
                
            chapter_number = chapter["chapter_number"]
            progress_value = i / generation_progress["total_chapters"]
            
            # Update progress information
            generation_progress["current_chapter"] = chapter_number
            time_est = calculate_estimated_completion_time()
            progress_desc = f"Generating Chapter {chapter_number} - {time_est}"
            
            # Update progress display
            progress(progress_value, desc=progress_desc)
            log_message(f"Generating Chapter {chapter_number}: {chapter['title']}...")
            log_message(update_progress_info())
            
            # Generate the chapter
            result = generate_chapter(chapter_number, chapter, model_name)
            log_message(result)
            
            # Update progress counters
            generation_progress["completed_chapters"] += 1
            
            # Auto-save metadata after each chapter
            save_book_metadata()
            
            # Allow a short pause between chapters
            time.sleep(1)
        
        progress(1.0, desc="Selected chapter generation complete")
        log_message("v Selected chapter generation complete!")
        
    except Exception as e:
        error_msg = f"Error generating chapters: {str(e)}"
        logger.error(error_msg, exc_info=True)
        log_message(error_msg)
    
    finally:
        generation_active = False

def start_book_generation(model_name, progress=gr.Progress()):
    """Start book generation in a separate thread"""
    global generation_active, generation_thread
    
    if generation_active:
        return log_message("Book generation already in progress!")
    
    generation_active = True
    generation_thread = threading.Thread(
        target=generate_book_thread, 
        args=(model_name, progress)
    )
    generation_thread.start()
    
    return log_message("Book generation started in background...")

def start_selected_chapter_generation(chapter_numbers, model_name, progress=gr.Progress()):
    """Start generation of selected chapters in a separate thread"""
    global generation_active, generation_thread
    
    if generation_active:
        return log_message("Book generation already in progress!")
    
    generation_active = True
    generation_thread = threading.Thread(
        target=generate_selected_chapters, 
        args=(chapter_numbers, model_name, progress)
    )
    generation_thread.start()
    
    return log_message("Selected chapter generation started in background...")

def stop_generation():
    """Stop the book generation process"""
    global generation_active
    generation_active = False
    return log_message("Book generation canceled. Currently running chapter will complete before stopping.")

def combine_book():
    """Combine all generated chapters into a single file"""
    try:
        if not current_book_folder:
            return log_message("No active book project. Please create or load a book project first.")
        
        book_text = f"# {current_book_title}\n\n"
        chapter_files = sorted([f for f in os.listdir(current_book_folder) 
                              if f.startswith("chapter_") and f.endswith(".txt")])
        
        if not chapter_files:
            return log_message("No chapters found to combine!")
        
        for file in chapter_files:
            with open(os.path.join(current_book_folder, file), "r", encoding="utf-8") as f:
                book_text += f.read() + "\n\n"
        
        # Write the combined book
        full_book_path = os.path.join(current_book_folder, "full_book.txt")
        with open(full_book_path, "w", encoding="utf-8") as f:
            f.write(book_text)
        
        return log_message(f"v Book combined successfully! Saved to {full_book_path}")
    
    except Exception as e:
        error_msg = f"Error combining book: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return log_message(error_msg)

# World Building Functions
def add_world_building_entry(category, content):
    """Add a world building entry to the current book project"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return "", msg
        
        # Add the entry to the world building data
        if "world_building" not in current_book_data:
            current_book_data["world_building"] = {}
        
        current_book_data["world_building"][category] = content
        
        # Save the updated metadata
        save_book_metadata()
        
        # Save to database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Generate a unique ID for the world building entry
                entry_id = str(uuid.uuid4())
                
                # Check if entry already exists
                cursor.execute(
                    "SELECT id FROM world_building WHERE project_id = ? AND category = ? AND subcategory IS NULL AND name = ?",
                    (current_book_id, category, category)
                )
                existing_entry = cursor.fetchone()
                
                if existing_entry:
                    # Update existing entry
                    cursor.execute(
                        "UPDATE world_building SET content = ? WHERE id = ?",
                        (content, existing_entry[0])
                    )
                else:
                    # Insert new entry
                    cursor.execute(
                        "INSERT INTO world_building (id, project_id, category, name, content) VALUES (?, ?, ?, ?, ?)",
                        (entry_id, current_book_id, category, category, content)
                    )
                
                conn.commit()
        
        # Format the current world building data for display
        world_data_formatted = get_world_building_display()
        
        msg = f"v Added world building entry: {category}"
        log_message(msg)
        return world_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error adding world building entry: {str(e)}"
        log_message(error_msg)
        return "", error_msg

def add_world_building_element(category, subcategory, name, content):
    """Add a hierarchical world building element"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return "", msg
        
        # Initialize world building structure if it doesn't exist
        if "world_building_hierarchy" not in current_book_data:
            current_book_data["world_building_hierarchy"] = {}
        
        # Initialize category if it doesn't exist
        if category not in current_book_data["world_building_hierarchy"]:
            current_book_data["world_building_hierarchy"][category] = {}
        
        # Initialize subcategory if it doesn't exist
        if subcategory not in current_book_data["world_building_hierarchy"][category]:
            current_book_data["world_building_hierarchy"][category][subcategory] = {}
        
        # Add the element
        current_book_data["world_building_hierarchy"][category][subcategory][name] = content
        
        # Save the updated metadata
        save_book_metadata()
        
        # Save to database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Generate a unique ID for the world building entry
                entry_id = str(uuid.uuid4())
                
                # Check if entry already exists
                cursor.execute(
                    "SELECT id FROM world_building WHERE project_id = ? AND category = ? AND subcategory = ? AND name = ?",
                    (current_book_id, category, subcategory, name)
                )
                existing_entry = cursor.fetchone()
                
                if existing_entry:
                    # Update existing entry
                    cursor.execute(
                        "UPDATE world_building SET content = ? WHERE id = ?",
                        (content, existing_entry[0])
                    )
                else:
                    # Insert new entry
                    cursor.execute(
                        "INSERT INTO world_building (id, project_id, category, subcategory, name, content) VALUES (?, ?, ?, ?, ?, ?)",
                        (entry_id, current_book_id, category, subcategory, name, content)
                    )
                
                conn.commit()
        
        # Format the current world building data for display
        world_data_formatted = get_world_building_hierarchy_display()
        
        msg = f"v Added world building element: {category}/{subcategory}/{name}"
        log_message(msg)
        return world_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error adding world building element: {str(e)}"
        log_message(error_msg)
        return "", error_msg

def edit_world_building_entry(category, new_content):
    """Edit an existing world building entry in the current book project"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return "", msg
        
        # Check if the category exists
        if "world_building" not in current_book_data or category not in current_book_data["world_building"]:
            msg = f"Category '{category}' not found in world building data."
            log_message(msg)
            return "", msg
        
        # Update the entry
        current_book_data["world_building"][category] = new_content
        
        # Save the updated metadata
        save_book_metadata()
        
        # Update in database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "UPDATE world_building SET content = ? WHERE project_id = ? AND category = ? AND subcategory IS NULL AND name = ?",
                    (new_content, current_book_id, category, category)
                )
                conn.commit()
        
        # Format the current world building data for display
        world_data_formatted = get_world_building_display()
        
        msg = f"v Updated world building entry: {category}"
        log_message(msg)
        return world_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error updating world building entry: {str(e)}"
        log_message(error_msg)
        return "", error_msg

def edit_world_building_element(category, subcategory, name, new_content):
    """Edit a hierarchical world building element"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return "", msg
        
        # Check if the element exists
        if ("world_building_hierarchy" not in current_book_data or
            category not in current_book_data["world_building_hierarchy"] or
            subcategory not in current_book_data["world_building_hierarchy"][category] or
            name not in current_book_data["world_building_hierarchy"][category][subcategory]):
            msg = f"Element '{category}/{subcategory}/{name}' not found in world building data."
            log_message(msg)
            return "", msg
        
        # Update the element
        current_book_data["world_building_hierarchy"][category][subcategory][name] = new_content
        
        # Save the updated metadata
        save_book_metadata()
        
        # Update in database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "UPDATE world_building SET content = ? WHERE project_id = ? AND category = ? AND subcategory = ? AND name = ?",
                    (new_content, current_book_id, category, subcategory, name)
                )
                conn.commit()
        
        # Format the current world building data for display
        world_data_formatted = get_world_building_hierarchy_display()
        
        msg = f"v Updated world building element: {category}/{subcategory}/{name}"
        log_message(msg)
        return world_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error updating world building element: {str(e)}"
        log_message(error_msg)
        return "", error_msg

def delete_world_building_entry(category):
    """Delete a world building entry from the current book project"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return "", msg
        
        # Check if the category exists
        if "world_building" not in current_book_data or category not in current_book_data["world_building"]:
            msg = f"Category '{category}' not found in world building data."
            log_message(msg)
            return "", msg
        
        # Delete the entry
        del current_book_data["world_building"][category]
        
        # Save the updated metadata
        save_book_metadata()
        
        # Delete from database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "DELETE FROM world_building WHERE project_id = ? AND category = ? AND subcategory IS NULL AND name = ?",
                    (current_book_id, category, category)
                )
                conn.commit()
        
        # Format the current world building data for display
        world_data_formatted = get_world_building_display()
        
        msg = f"v Deleted world building entry: {category}"
        log_message(msg)
        return world_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error deleting world building entry: {str(e)}"
        log_message(error_msg)
        return "", error_msg

def delete_world_building_element(category, subcategory, name):
    """Delete a hierarchical world building element"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return "", msg
        
        # Check if the element exists
        if ("world_building_hierarchy" not in current_book_data or
            category not in current_book_data["world_building_hierarchy"] or
            subcategory not in current_book_data["world_building_hierarchy"][category] or
            name not in current_book_data["world_building_hierarchy"][category][subcategory]):
            msg = f"Element '{category}/{subcategory}/{name}' not found in world building data."
            log_message(msg)
            return "", msg
        
        # Delete the element
        del current_book_data["world_building_hierarchy"][category][subcategory][name]
        
        # Delete the subcategory if it's empty
        if not current_book_data["world_building_hierarchy"][category][subcategory]:
            del current_book_data["world_building_hierarchy"][category][subcategory]
            
            # Delete the category if it's empty
            if not current_book_data["world_building_hierarchy"][category]:
                del current_book_data["world_building_hierarchy"][category]
        
        # Save the updated metadata
        save_book_metadata()
        
        # Delete from database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "DELETE FROM world_building WHERE project_id = ? AND category = ? AND subcategory = ? AND name = ?",
                    (current_book_id, category, subcategory, name)
                )
                conn.commit()
        
        # Format the current world building data for display
        world_data_formatted = get_world_building_hierarchy_display()
        
        msg = f"v Deleted world building element: {category}/{subcategory}/{name}"
        log_message(msg)
        return world_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error deleting world building element: {str(e)}"
        log_message(error_msg)
        return "", error_msg

def get_world_building_categories():
    """Get a list of all world building categories in the current book project"""
    if not current_book_folder or "world_building" not in current_book_data:
        return ["No categories available"]
    
    categories = list(current_book_data["world_building"].keys())
    if not categories:
        return ["No categories available"]
    
    return ["Select a category"] + categories

def get_world_building_hierarchy_categories():
    """Get a list of all hierarchical world building categories"""
    if not current_book_folder or "world_building_hierarchy" not in current_book_data:
        return ["No categories available"]
    
    categories = list(current_book_data["world_building_hierarchy"].keys())
    if not categories:
        return ["No categories available"]
    
    return ["Select a category"] + categories

def get_world_building_subcategories(category):
    """Get a list of all subcategories for a given category"""
    if (not current_book_folder or 
        "world_building_hierarchy" not in current_book_data or 
        category not in current_book_data["world_building_hierarchy"]):
        return ["No subcategories available"]
    
    subcategories = list(current_book_data["world_building_hierarchy"][category].keys())
    if not subcategories:
        return ["No subcategories available"]
    
    return ["Select a subcategory"] + subcategories

def get_world_building_elements(category, subcategory):
    """Get a list of all elements for a given category and subcategory"""
    if (not current_book_folder or 
        "world_building_hierarchy" not in current_book_data or 
        category not in current_book_data["world_building_hierarchy"] or
        subcategory not in current_book_data["world_building_hierarchy"][category]):
        return ["No elements available"]
    
    elements = list(current_book_data["world_building_hierarchy"][category][subcategory].keys())
    if not elements:
        return ["No elements available"]
    
    return ["Select an element"] + elements

def get_world_building_content(category):
    """Get the content of a specific world building category"""
    if not current_book_folder or "world_building" not in current_book_data:
        return ""
    
    if category in current_book_data["world_building"]:
        return current_book_data["world_building"][category]
    
    return ""

def get_world_building_element_content(category, subcategory, name):
    """Get the content of a specific world building element"""
    if (not current_book_folder or 
        "world_building_hierarchy" not in current_book_data or 
        category not in current_book_data["world_building_hierarchy"] or
        subcategory not in current_book_data["world_building_hierarchy"][category] or
        name not in current_book_data["world_building_hierarchy"][category][subcategory]):
        return ""
    
    return current_book_data["world_building_hierarchy"][category][subcategory][name]

def get_world_building_display():
    """Format world building data for display"""
    if not current_book_folder or "world_building" not in current_book_data or not current_book_data["world_building"]:
        return "# World Building Information\n\nNo world building elements defined yet."
    
    # Format the current world building data for display
    world_data_formatted = "# World Building Information\n\n"
    for key, value in current_book_data["world_building"].items():
        world_data_formatted += f"## {key}\n{value}\n\n"
    
    return world_data_formatted

def get_world_building_hierarchy_display():
    """Format hierarchical world building data for display"""
    if not current_book_folder or "world_building_hierarchy" not in current_book_data or not current_book_data["world_building_hierarchy"]:
        return "# World Building Hierarchy\n\nNo hierarchical world building elements defined yet."
    
    # Format the current world building hierarchy for display
    world_data_formatted = "# World Building Hierarchy\n\n"
    for category, subcategories in current_book_data["world_building_hierarchy"].items():
        world_data_formatted += f"## {category}\n\n"
        for subcategory, elements in subcategories.items():
            world_data_formatted += f"### {subcategory}\n\n"
            for name, content in elements.items():
                world_data_formatted += f"#### {name}\n{content}\n\n"
    
    return world_data_formatted

# Character Functions
def add_character(name, description):
    """Add a character to the current book project"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return "", msg
        
        # Add the character to the data
        if "characters" not in current_book_data:
            current_book_data["characters"] = {}
        
        current_book_data["characters"][name] = description
        
        # Save the updated metadata
        save_book_metadata()
        
        # Save to database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Generate a unique ID for the character
                character_id = str(uuid.uuid4())
                
                # Check if character already exists
                cursor.execute(
                    "SELECT id FROM characters WHERE project_id = ? AND name = ?",
                    (current_book_id, name)
                )
                existing_character = cursor.fetchone()
                
                if existing_character:
                    # Update existing character
                    cursor.execute(
                        "UPDATE characters SET description = ? WHERE id = ?",
                        (description, existing_character[0])
                    )
                else:
                    # Insert new character
                    cursor.execute(
                        "INSERT INTO characters (id, project_id, name, description) VALUES (?, ?, ?, ?)",
                        (character_id, current_book_id, name, description)
                    )
                
                conn.commit()
        
        # Format the current character data for display
        char_data_formatted = get_characters_display()
        
        msg = f"v Added character: {name}"
        log_message(msg)
        return char_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error adding character: {str(e)}"
        log_message(error_msg)
        return "", error_msg

def add_character_relationship(character1, character2, relationship_type, description):
    """Add a relationship between two characters"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return "", msg
        
        # Check if characters exist
        if "characters" not in current_book_data:
            msg = "No characters defined yet. Please add characters first."
            log_message(msg)
            return "", msg
        
        if character1 not in current_book_data["characters"]:
            msg = f"Character '{character1}' not found. Please add this character first."
            log_message(msg)
            return "", msg
        
        if character2 not in current_book_data["characters"]:
            msg = f"Character '{character2}' not found. Please add this character first."
            log_message(msg)
            return "", msg
        
        # Initialize relationships list if it doesn't exist
        if "character_relationships" not in current_book_data:
            current_book_data["character_relationships"] = []
        
        # Add the relationship
        relationship = {
            "character1": character1,
            "character2": character2,
            "type": relationship_type,
            "description": description
        }
        
        # Check if relationship already exists
        existing_rel = False
        for i, rel in enumerate(current_book_data["character_relationships"]):
            if rel["character1"] == character1 and rel["character2"] == character2:
                current_book_data["character_relationships"][i] = relationship
                existing_rel = True
                break
            elif rel["character1"] == character2 and rel["character2"] == character1:
                current_book_data["character_relationships"][i] = relationship
                existing_rel = True
                break
        
        if not existing_rel:
            current_book_data["character_relationships"].append(relationship)
        
        # Save the updated metadata
        save_book_metadata()
        
        # Save to database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Get character IDs
                cursor.execute("SELECT id FROM characters WHERE project_id = ? AND name = ?", (current_book_id, character1))
                char1_id = cursor.fetchone()[0]
                
                cursor.execute("SELECT id FROM characters WHERE project_id = ? AND name = ?", (current_book_id, character2))
                char2_id = cursor.fetchone()[0]
                
                # Generate a unique ID for the relationship
                relationship_id = str(uuid.uuid4())
                
                # Check if relationship already exists
                cursor.execute(
                    """
                    SELECT id FROM character_relationships 
                    WHERE project_id = ? AND 
                    ((character1_id = ? AND character2_id = ?) OR (character1_id = ? AND character2_id = ?))
                    """,
                    (current_book_id, char1_id, char2_id, char2_id, char1_id)
                )
                existing_rel_id = cursor.fetchone()
                
                if existing_rel_id:
                    # Update existing relationship
                    cursor.execute(
                        "UPDATE character_relationships SET relationship_type = ?, description = ? WHERE id = ?",
                        (relationship_type, description, existing_rel_id[0])
                    )
                else:
                    # Insert new relationship
                    cursor.execute(
                        """
                        INSERT INTO character_relationships 
                        (id, project_id, character1_id, character2_id, relationship_type, description) 
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (relationship_id, current_book_id, char1_id, char2_id, relationship_type, description)
                    )
                
                conn.commit()
        
        # Format the current character relationships for display
        rel_data_formatted = get_character_relationships_display()
        
        msg = f"v Added relationship between {character1} and {character2}"
        log_message(msg)
        return rel_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error adding character relationship: {str(e)}"
        log_message(error_msg)
        return "", error_msg

def add_character_arc(character_name, arc_points):
    """Add a character development arc"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return "", msg
        
        # Check if the character exists
        if "characters" not in current_book_data or character_name not in current_book_data["characters"]:
            msg = f"Character '{character_name}' not found. Please add this character first."
            log_message(msg)
            return "", msg
        
        # Initialize character arcs dict if it doesn't exist
        if "character_arcs" not in current_book_data:
            current_book_data["character_arcs"] = {}
        
        # Add the character arc
        current_book_data["character_arcs"][character_name] = arc_points
        
        # Save the updated metadata
        save_book_metadata()
        
        # Save to database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Get character ID
                cursor.execute("SELECT id FROM characters WHERE project_id = ? AND name = ?", (current_book_id, character_name))
                character_id = cursor.fetchone()[0]
                
                # Delete existing arc points for this character
                cursor.execute("DELETE FROM character_arcs WHERE character_id = ?", (character_id,))
                
                # Add new arc points
                for i, point in enumerate(arc_points.split("\n")):
                    if point.strip():
                        # Generate a unique ID for the arc point
                        arc_id = str(uuid.uuid4())
                        
                        cursor.execute(
                            "INSERT INTO character_arcs (id, character_id, arc_point, description) VALUES (?, ?, ?, ?)",
                            (arc_id, character_id, i+1, point.strip())
                        )
                
                conn.commit()
        
        # Format the current character arcs for display
        arc_data_formatted = get_character_arcs_display()
        
        msg = f"v Added development arc for {character_name}"
        log_message(msg)
        return arc_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error adding character arc: {str(e)}"
        log_message(error_msg)
        return "", error_msg

def edit_character(name, new_description):
    """Edit an existing character in the current book project"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return "", msg
        
        # Check if the character exists
        if "characters" not in current_book_data or name not in current_book_data["characters"]:
            msg = f"Character '{name}' not found in character data."
            log_message(msg)
            return "", msg
        
        # Update the character
        current_book_data["characters"][name] = new_description
        
        # Save the updated metadata
        save_book_metadata()
        
        # Update in database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    "UPDATE characters SET description = ? WHERE project_id = ? AND name = ?",
                    (new_description, current_book_id, name)
                )
                conn.commit()
        
        # Format the current character data for display
        char_data_formatted = get_characters_display()
        
        msg = f"v Updated character: {name}"
        log_message(msg)
        return char_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error updating character: {str(e)}"
        log_message(error_msg)
        return "", error_msg

def delete_character(name):
    """Delete a character from the current book project"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return "", msg
        
        # Check if the character exists
        if "characters" not in current_book_data or name not in current_book_data["characters"]:
            msg = f"Character '{name}' not found in character data."
            log_message(msg)
            return "", msg
        
        # Delete the character
        del current_book_data["characters"][name]
        
        # Delete any relationships involving this character
        if "character_relationships" in current_book_data:
            current_book_data["character_relationships"] = [
                rel for rel in current_book_data["character_relationships"]
                if rel["character1"] != name and rel["character2"] != name
            ]
        
        # Delete any character arcs for this character
        if "character_arcs" in current_book_data and name in current_book_data["character_arcs"]:
            del current_book_data["character_arcs"][name]
        
        # Save the updated metadata
        save_book_metadata()
        
        # Delete from database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Get character ID first
                cursor.execute("SELECT id FROM characters WHERE project_id = ? AND name = ?", (current_book_id, name))
                result = cursor.fetchone()
                
                if result:
                    character_id = result[0]
                    
                    # Delete character arcs
                    cursor.execute("DELETE FROM character_arcs WHERE character_id = ?", (character_id,))
                    
                    # Delete character relationships
                    cursor.execute(
                        """
                        DELETE FROM character_relationships 
                        WHERE character1_id = ? OR character2_id = ?
                        """,
                        (character_id, character_id)
                    )
                    
                    # Delete character
                    cursor.execute("DELETE FROM characters WHERE id = ?", (character_id,))
                    
                    conn.commit()
        
        # Format the current character data for display
        char_data_formatted = get_characters_display()
        
        msg = f"v Deleted character: {name}"
        log_message(msg)
        return char_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error deleting character: {str(e)}"
        log_message(error_msg)
        return "", error_msg

def get_character_names():
    """Get a list of all character names in the current book project"""
    if not current_book_folder or "characters" not in current_book_data:
        return ["No characters available"]
    
    names = list(current_book_data["characters"].keys())
    if not names:
        return ["No characters available"]
    
    return ["Select a character"] + names

def get_character_description(name):
    """Get the description of a specific character"""
    if not current_book_folder or "characters" not in current_book_data:
        return ""
    
    if name in current_book_data["characters"]:
        return current_book_data["characters"][name]
    
    return ""

def get_character_arc(name):
    """Get the development arc of a specific character"""
    if not current_book_folder or "character_arcs" not in current_book_data:
        return ""
    
    if name in current_book_data["character_arcs"]:
        return current_book_data["character_arcs"][name]
    
    return ""

def get_characters_display():
    """Format character data for display"""
    if not current_book_folder or "characters" not in current_book_data or not current_book_data["characters"]:
        return "# Characters\n\nNo characters defined yet."
    
    # Format the current character data for display
    char_data_formatted = "# Characters\n\n"
    for name, desc in current_book_data["characters"].items():
        char_data_formatted += f"## {name}\n{desc}\n\n"
    
    return char_data_formatted

def get_character_relationships_display():
    """Format character relationships for display"""
    if not current_book_folder or "character_relationships" not in current_book_data or not current_book_data["character_relationships"]:
        return "# Character Relationships\n\nNo character relationships defined yet."
    
    # Format the current character relationships for display
    rel_data_formatted = "# Character Relationships\n\n"
    for rel in current_book_data["character_relationships"]:
        rel_data_formatted += f"## {rel['character1']} & {rel['character2']}\n"
        rel_data_formatted += f"**Type:** {rel['type']}\n\n"
        rel_data_formatted += f"{rel['description']}\n\n"
    
    return rel_data_formatted

def get_character_arcs_display():
    """Format character arcs for display"""
    if not current_book_folder or "character_arcs" not in current_book_data or not current_book_data["character_arcs"]:
        return "# Character Development Arcs\n\nNo character arcs defined yet."
    
    # Format the current character arcs for display
    arc_data_formatted = "# Character Development Arcs\n\n"
    for name, arc in current_book_data["character_arcs"].items():
        arc_data_formatted += f"## {name}'s Arc\n{arc}\n\n"
    
    return arc_data_formatted

# Target Audience Functions
def set_target_audience(age_min, age_max, reading_level, neurodivergent_accommodations=None, content_guidelines=None):
    """Set target audience specifications for the current book project"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return msg
        
        # Create audience specification
        audience_spec = {
            "age_min": age_min,
            "age_max": age_max,
            "reading_level": reading_level,
            "accommodations": neurodivergent_accommodations or [],
            "content_guidelines": content_guidelines or []
        }
        
        # Update book data
        current_book_data["target_audience"] = audience_spec
        
        # Save the updated metadata
        save_book_metadata()
        
        # Update in database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Check if target audience already exists for this project
                cursor.execute("SELECT project_id FROM target_audience WHERE project_id = ?", (current_book_id,))
                existing_audience = cursor.fetchone()
                
                if existing_audience:
                    # Update existing audience
                    cursor.execute(
                        "UPDATE target_audience SET age_min = ?, age_max = ?, reading_level = ? WHERE project_id = ?",
                        (age_min, age_max, reading_level, current_book_id)
                    )
                else:
                    # Insert new audience
                    cursor.execute(
                        "INSERT INTO target_audience (project_id, age_min, age_max, reading_level) VALUES (?, ?, ?, ?)",
                        (current_book_id, age_min, age_max, reading_level)
                    )
                
                # Delete existing accommodations
                cursor.execute("DELETE FROM audience_accommodations WHERE project_id = ?", (current_book_id,))
                
                # Add new accommodations
                if neurodivergent_accommodations:
                    for accom in neurodivergent_accommodations:
                        accom_id = str(uuid.uuid4())
                        cursor.execute(
                            "INSERT INTO audience_accommodations (id, project_id, accommodation_type, description) VALUES (?, ?, ?, ?)",
                            (accom_id, current_book_id, accom["type"], accom["description"])
                        )
                
                conn.commit()
        
        msg = f"v Set target audience specifications for '{current_book_title}'"
        log_message(msg)
        return msg
    
    except Exception as e:
        error_msg = f"Error setting target audience: {str(e)}"
        log_message(error_msg)
        return error_msg

def add_neurodivergent_accommodation(accommodation_type, description):
    """Add a neurodivergent accommodation to the target audience"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return msg
        
        # Ensure target audience exists
        if "target_audience" not in current_book_data:
            current_book_data["target_audience"] = {
                "age_min": 0,
                "age_max": 99,
                "reading_level": "General",
                "accommodations": [],
                "content_guidelines": []
            }
        
        # Ensure accommodations list exists
        if "accommodations" not in current_book_data["target_audience"]:
            current_book_data["target_audience"]["accommodations"] = []
        
        # Add the accommodation
        accommodation = {
            "type": accommodation_type,
            "description": description
        }
        
        current_book_data["target_audience"]["accommodations"].append(accommodation)
        
        # Save the updated metadata
        save_book_metadata()
        
        # Add to database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Check if target audience exists
                cursor.execute("SELECT project_id FROM target_audience WHERE project_id = ?", (current_book_id,))
                existing_audience = cursor.fetchone()
                
                if not existing_audience:
                    # Insert basic target audience
                    cursor.execute(
                        """
                        INSERT INTO target_audience (project_id, age_min, age_max, reading_level) 
                        VALUES (?, ?, ?, ?)
                        """,
                        (current_book_id, 0, 99, "General")
                    )
                
                # Insert accommodation
                accom_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO audience_accommodations (id, project_id, accommodation_type, description) 
                    VALUES (?, ?, ?, ?)
                    """,
                    (accom_id, current_book_id, accommodation_type, description)
                )
                
                conn.commit()
        
        msg = f"v Added neurodivergent accommodation: {accommodation_type}"
        log_message(msg)
        return msg
    
    except Exception as e:
        error_msg = f"Error adding neurodivergent accommodation: {str(e)}"
        log_message(error_msg)
        return error_msg

def add_content_guideline(guideline):
    """Add a content guideline to the target audience"""
    global current_book_data
    
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return msg
        
        # Ensure target audience exists
        if "target_audience" not in current_book_data:
            current_book_data["target_audience"] = {
                "age_min": 0,
                "age_max": 99,
                "reading_level": "General",
                "accommodations": [],
                "content_guidelines": []
            }
        
        # Ensure content guidelines list exists
        if "content_guidelines" not in current_book_data["target_audience"]:
            current_book_data["target_audience"]["content_guidelines"] = []
        
        # Add the guideline
        current_book_data["target_audience"]["content_guidelines"].append(guideline)
        
        # Save the updated metadata
        save_book_metadata()
        
        # We won't add this to the database since we don't have a dedicated table for it
        
        msg = f"v Added content guideline"
        log_message(msg)
        return msg
    
    except Exception as e:
        error_msg = f"Error adding content guideline: {str(e)}"
        log_message(error_msg)
        return error_msg

def get_target_audience_display():
    """Format target audience data for display"""
    if not current_book_folder or "target_audience" not in current_book_data:
        return "# Target Audience\n\nNo target audience specifications defined yet."
    
    audience = current_book_data["target_audience"]
    
    # Format the target audience for display
    audience_formatted = "# Target Audience\n\n"
    
    # Age range
    if "age_min" in audience and "age_max" in audience:
        audience_formatted += f"## Age Range\n{audience['age_min']}-{audience['age_max']} years\n\n"
    
    # Reading level
    if "reading_level" in audience:
        audience_formatted += f"## Reading Level\n{audience['reading_level']}\n\n"
    
    # Neurodivergent accommodations
    if "accommodations" in audience and audience["accommodations"]:
        audience_formatted += "## Neurodivergent Accommodations\n"
        for accom in audience["accommodations"]:
            audience_formatted += f"### {accom['type']}\n{accom['description']}\n\n"
    
    # Content guidelines
    if "content_guidelines" in audience and audience["content_guidelines"]:
        audience_formatted += "## Content Guidelines\n"
        for guideline in audience["content_guidelines"]:
            audience_formatted += f"- {guideline}\n"
    
    return audience_formatted

# Flowchart Input Organization
def process_flowchart_input(flowchart_data):
    """Process flowchart input and distribute to appropriate categories"""
    try:
        if not current_book_folder:
            msg = "No active book project. Please create or load a book project first."
            log_message(msg)
            return msg
        
        # Parse the flowchart data
        nodes = flowchart_data.get("nodes", [])
        connections = flowchart_data.get("connections", [])
        
        # Categorize nodes based on content and connections
        world_building_elements = []
        character_elements = []
        plot_elements = []
        setting_elements = []
        
        # Simple categorization based on keywords
        for node in nodes:
            content = node.get("content", "")
            node_id = node.get("id")
            
            # Categorize based on content keywords
            if any(kw in content.lower() for kw in ["person", "character", "protagonist", "antagonist"]):
                character_elements.append((node_id, content))
            elif any(kw in content.lower() for kw in ["world", "system", "rule", "magic", "technology"]):
                world_building_elements.append((node_id, content))
            elif any(kw in content.lower() for kw in ["plot", "event", "conflict", "resolution"]):
                plot_elements.append((node_id, content))
            elif any(kw in content.lower() for kw in ["place", "location", "setting", "geography"]):
                setting_elements.append((node_id, content))
        
        # Process each category
        added_elements = []
        
        # Add characters
        for node_id, content in character_elements:
            # Extract character name (first line or up to first colon)
            name = content.split('\n')[0].split(':')[0].strip()
            description = content.replace(name, "", 1).strip()
            if description.startswith(":"):
                description = description[1:].strip()
            
            if name and name not in current_book_data.get("characters", {}):
                add_character(name, description)
                added_elements.append(f"Character: {name}")
        
        # Add world building elements
        for node_id, content in world_building_elements:
            # Extract category name (first line or up to first colon)
            category = content.split('\n')[0].split(':')[0].strip()
            description = content.replace(category, "", 1).strip()
            if description.startswith(":"):
                description = description[1:].strip()
            
            if category and category not in current_book_data.get("world_building", {}):
                add_world_building_entry(category, description)
                added_elements.append(f"World Building: {category}")
        
        # Add setting elements to world building
        for node_id, content in setting_elements:
            category = "Settings"
            subcategory = content.split('\n')[0].split(':')[0].strip()
            description = content.replace(subcategory, "", 1).strip()
            if description.startswith(":"):
                description = description[1:].strip()
            
            if subcategory:
                add_world_building_element(category, "Locations", subcategory, description)
                added_elements.append(f"Setting: {subcategory}")
        
        # Process plot elements into outline if needed
        if plot_elements and not current_outline:
            # Create a simple outline from plot elements
            chapters = []
            for i, (node_id, content) in enumerate(plot_elements, 1):
                title = content.split('\n')[0].strip()
                chapter_info = {
                    "chapter_number": i,
                    "title": title,
                    "prompt": content
                }
                chapters.append(chapter_info)
            
            current_book_data["chapters"] = chapters
            current_outline = chapters
            save_book_metadata()
            added_elements.append("Plot outline (converted to chapters)")
        
        msg = f"v Processed flowchart input and added {len(added_elements)} elements"
        log_message(msg)
        return msg + "\n\n" + "\n".join(added_elements)
    
    except Exception as e:
        error_msg = f"Error processing flowchart input: {str(e)}"
        log_message(error_msg)
        return error_msg

def find_and_replace(old_text, new_text):
    """Find and replace text across all chapters in the current book project"""
    try:
        if not current_book_folder:
            return log_message("No active book project. Please create or load a book project first.")
        
        if not old_text:
            return log_message("Please provide text to find.")
        
        # Find all chapter files
        chapter_files = sorted([f for f in os.listdir(current_book_folder) 
                              if f.startswith("chapter_") and f.endswith(".txt")])
        
        if not chapter_files:
            return log_message("No chapters found to perform find and replace!")
        
        # Count replacements
        total_replacements = 0
        modified_files = 0
        
        # Process each file
        for file in chapter_files:
            file_path = os.path.join(current_book_folder, file)
            
            # Read the content
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Perform the replacement
            new_content, count = re.subn(re.escape(old_text), new_text, content)
            
            # If replacements were made, save the updated content
            if count > 0:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                
                total_replacements += count
                modified_files += 1
        
        # Also check full_book.txt if it exists
        full_book_path = os.path.join(current_book_folder, "full_book.txt")
        if os.path.exists(full_book_path):
            # Read the content
            with open(full_book_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Perform the replacement
            new_content, count = re.subn(re.escape(old_text), new_text, content)
            
            # If replacements were made, save the updated content
            if count > 0:
                with open(full_book_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                
                total_replacements += count
                modified_files += 1
        
        # Update metadata if necessary (for character names, etc.)
        metadata_updated = False
        
        # Update character names
        if "characters" in current_book_data:
            if old_text in current_book_data["characters"]:
                current_book_data["characters"][new_text] = current_book_data["characters"].pop(old_text)
                metadata_updated = True
                
                # Update the name in the database
                with closing(sqlite3.connect('book_projects.db')) as conn:
                    with closing(conn.cursor()) as cursor:
                        cursor.execute(
                            "UPDATE characters SET name = ? WHERE project_id = ? AND name = ?",
                            (new_text, current_book_id, old_text)
                        )
                        conn.commit()
        
        # Update world building entries
        if "world_building" in current_book_data:
            if old_text in current_book_data["world_building"]:
                current_book_data["world_building"][new_text] = current_book_data["world_building"].pop(old_text)
                metadata_updated = True
                
                # Update the name in the database
                with closing(sqlite3.connect('book_projects.db')) as conn:
                    with closing(conn.cursor()) as cursor:
                        cursor.execute(
                            "UPDATE world_building SET name = ?, category = ? WHERE project_id = ? AND name = ? AND category = ?",
                            (new_text, new_text, current_book_id, old_text, old_text)
                        )
                        conn.commit()
        
        # Also update in the database for chapter content
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Update chapter content
                cursor.execute(
                    "UPDATE chapters SET content = REPLACE(content, ?, ?) WHERE project_id = ?",
                    (old_text, new_text, current_book_id)
                )
                
                # Update chapter outlines
                cursor.execute(
                    "UPDATE chapters SET outline = REPLACE(outline, ?, ?) WHERE project_id = ?",
                    (old_text, new_text, current_book_id)
                )
                
                conn.commit()
        
        # Save metadata if updated
        if metadata_updated:
            save_book_metadata()
        
        return log_message(f"v Replaced '{old_text}' with '{new_text}' ({total_replacements} replacements in {modified_files} files)")
    
    except Exception as e:
        error_msg = f"Error performing find and replace: {str(e)}"
        return log_message(error_msg)

def update_chapter_content(chapter_number, new_content):
    """Update the content of a specific chapter"""
    try:
        if not current_book_folder:
            return log_message("No active book project. Please create or load a book project first.")
        
        # Find the chapter file
        chapter_file = f"chapter_{int(chapter_number):02d}.txt"
        chapter_path = os.path.join(current_book_folder, chapter_file)
        
        if not os.path.exists(chapter_path):
            return log_message(f"Chapter {chapter_number} not found.")
        
        # Save a backup
        backup_file = f"{chapter_file}.bak"
        backup_path = os.path.join(current_book_folder, backup_file)
        shutil.copy2(chapter_path, backup_path)
        
        # Update the chapter content
        with open(chapter_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        
        # Update in database as well
        with closing(sqlite3.connect('book_projects.db')) as conn:
            with closing(conn.cursor()) as cursor:
                # Extract just the content (not the title line)
                content_parts = new_content.split("\n\n", 1)
                if len(content_parts) > 1:
                    content_only = content_parts[1]
                else:
                    content_only = new_content
                
                cursor.execute(
                    "UPDATE chapters SET content = ? WHERE project_id = ? AND chapter_number = ?",
                    (content_only, current_book_id, chapter_number)
                )
                conn.commit()
        
        return log_message(f"v Updated Chapter {chapter_number}. Backup saved as {backup_file}")
    
    except Exception as e:
        error_msg = f"Error updating chapter: {str(e)}"
        return log_message(error_msg)

def get_chapter_content(chapter_number):
    """Get the content of a specific chapter"""
    try:
        if not current_book_folder:
            return "No active book project. Please create or load a book project first."
        
        # Find the chapter file
        chapter_file = f"chapter_{int(chapter_number):02d}.txt"
        chapter_path = os.path.join(current_book_folder, chapter_file)
        
        if not os.path.exists(chapter_path):
            return f"Chapter {chapter_number} not found."
        
        # Read the chapter content
        with open(chapter_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        return content
    
    except Exception as e:
        error_msg = f"Error getting chapter content: {str(e)}"
        return error_msg

def list_project_files():
    """List all files in the current book project"""
    try:
        if not current_book_folder:
            return "No active book project. Please create or load a book project first."
        
        files = os.listdir(current_book_folder)
        if not files:
            return "No files found in the current project."
        
        file_list = f"# Files in '{current_book_title}'\n\n"
        for file in sorted(files):
            file_path = os.path.join(current_book_folder, file)
            size = os.path.getsize(file_path) / 1024  # Size in KB
            file_list += f"- {file} ({size:.2f} KB)\n"
        
        return file_list
    
    except Exception as e:
        return f"Error listing files: {str(e)}"

def load_project_file_content(file_option):
    """Load and return the content of a selected file from the current project"""
    if not file_option or file_option == "Select a file":
        return "Please select a file to view."
    
    if not current_book_folder:
        return "No active book project. Please create or load a book project first."
    
    try:
        file_path = os.path.join(current_book_folder, file_option)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    
    except Exception as e:
        return f"Error loading file: {str(e)}"

def get_project_file_options():
    """Get list of files in the current book project for the dropdown"""
    try:
        if not current_book_folder:
            return ["Select a file"]
        
        files = ["Select a file"] + sorted(os.listdir(current_book_folder))
        return files
    except:
        return ["Select a file"]

def export_book_project(format_type="txt"):
    """Export the book in the selected format"""
    try:
        if not current_book_folder:
            return log_message("No active book project. Please create or load a book project first.")
        
        # First combine all chapters if not already done
        full_book_path = os.path.join(current_book_folder, "full_book.txt")
        if not os.path.exists(full_book_path):
            combine_book()
        
        # Create a sanitized filename for the exported book
        export_filename = sanitize_folder_name(current_book_title).replace("_", " ")
        
        # Read the combined book content
        with open(full_book_path, "r", encoding="utf-8") as f:
            book_content = f.read()
        
        # Process based on format type
        if format_type == "txt":
            # Plain text export
            export_path = os.path.join(current_book_folder, f"{export_filename}.txt")
            with open(export_path, "w", encoding="utf-8") as f:
                f.write(book_content)
            return log_message(f"v Book exported as text file: {export_path}")
        
        elif format_type == "markdown":
            # Markdown export (already in markdown format)
            export_path = os.path.join(current_book_folder, f"{export_filename}.md")
            with open(export_path, "w", encoding="utf-8") as f:
                f.write(book_content)
            return log_message(f"v Book exported as Markdown file: {export_path}")
        
        elif format_type == "pdf" and export_capabilities["pdf"]:
            # PDF export using reportlab
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.styles import getSampleStyleSheet
            
            export_path = os.path.join(current_book_folder, f"{export_filename}.pdf")
            
            # Parse the book content to extract chapters and text
            doc = SimpleDocTemplate(export_path, pagesize=letter)
            styles = getSampleStyleSheet()
            
            # Process the content
            story = []
            
            # Add the title
            title = current_book_title
            story.append(Paragraph(title, styles["Title"]))
            story.append(Spacer(1, 12))
            
            # Process each chapter
            chapter_pattern = re.compile(r"Chapter \d+: (.+?)(?=\n\n)")
            chapters = chapter_pattern.findall(book_content)
            content_parts = re.split(r"Chapter \d+: .+?\n\n", book_content)[1:]  # Skip the first part (book title)
            
            for i, (chapter_title, content) in enumerate(zip(chapters, content_parts), 1):
                # Add chapter heading
                story.append(Paragraph(f"Chapter {i}: {chapter_title}", styles["Heading1"]))
                story.append(Spacer(1, 12))
                
                # Add chapter content - split by paragraphs
                paragraphs = content.split("\n\n")
                for para in paragraphs:
                    if para.strip():
                        story.append(Paragraph(para, styles["Normal"]))
                        story.append(Spacer(1, 6))
                
                # Add page break between chapters
                if i < len(chapters):
                    story.append(Spacer(1, 12))
            
            # Build the PDF
            doc.build(story)
            
            return log_message(f"v Book exported as PDF file: {export_path}")
        
        elif format_type == "epub" and export_capabilities["epub"]:
            # EPUB export
            import ebooklib
            from ebooklib import epub
            
            export_path = os.path.join(current_book_folder, f"{export_filename}.epub")
            
            # Create a new EPUB book
            book = epub.EpubBook()
            
            # Set metadata
            book.set_identifier(f"ghostwriter-{current_book_id}")
            book.set_title(current_book_title)
            book.set_language('en')
            
            # Process the content
            chapter_pattern = re.compile(r"Chapter (\d+): (.+?)(?=\n\n)")
            matches = chapter_pattern.finditer(book_content)
            content_parts = re.split(r"Chapter \d+: .+?\n\n", book_content)[1:]  # Skip the first part (book title)
            
            chapters = []
            toc = []
            
            for i, (match, content) in enumerate(zip(matches, content_parts), 1):
                chapter_num = match.group(1)
                chapter_title = match.group(2)
                
                # Create chapter
                c = epub.EpubHtml(title=f"Chapter {chapter_num}: {chapter_title}", 
                                 file_name=f'chap_{chapter_num}.xhtml',
                                 lang='en')
                
                # Format content as HTML
                html_content = f"<h1>Chapter {chapter_num}: {chapter_title}</h1>"
                
                # Add paragraphs
                paragraphs = content.split("\n\n")
                for para in paragraphs:
                    if para.strip():
                        html_content += f"<p>{para}</p>"
                
                c.content = html_content
                book.add_item(c)
                chapters.append(c)
                toc.append(epub.Link(f'chap_{chapter_num}.xhtml', f'Chapter {chapter_num}: {chapter_title}', f'chap_{chapter_num}'))
            
            # Add chapters to the book
            book.toc = toc
            
            # Add default NCX and Nav files
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            
            # Define CSS
            style = '''
            @namespace epub "http://www.idpf.org/2007/ops";
            body {
                font-family: Cambria, Liberation Serif, Bitstream Vera Serif, Georgia, Times, Times New Roman, serif;
            }
            h1 {
                text-align: center;
                margin-bottom: 1em;
            }
            p {
                text-indent: 1em;
                margin-top: 0.5em;
                margin-bottom: 0.5em;
            }
            '''
            
            nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=style)
            book.add_item(nav_css)
            
            # Create spine
            book.spine = ['nav'] + chapters
            
            # Write the EPUB file
            epub.write_epub(export_path, book, {})
            
            return log_message(f"v Book exported as EPUB file: {export_path}")
        
        elif format_type == "docx" and export_capabilities["docx"]:
            # DOCX export
            from docx import Document
            
            export_path = os.path.join(current_book_folder, f"{export_filename}.docx")
            
            # Create a new Document
            doc = Document()
            
            # Add title
            doc.add_heading(current_book_title, 0)
            
            # Process the content
            chapter_pattern = re.compile(r"Chapter (\d+): (.+?)(?=\n\n)")
            matches = chapter_pattern.finditer(book_content)
            content_parts = re.split(r"Chapter \d+: .+?\n\n", book_content)[1:]  # Skip the first part (book title)
            
            for i, (match, content) in enumerate(zip(matches, content_parts), 1):
                chapter_num = match.group(1)
                chapter_title = match.group(2)
                
                # Add chapter heading
                doc.add_heading(f"Chapter {chapter_num}: {chapter_title}", 1)
                
                # Add paragraphs
                paragraphs = content.split("\n\n")
                for para in paragraphs:
                    if para.strip():
                        doc.add_paragraph(para)
            
            # Save the document
            doc.save(export_path)
            
            return log_message(f"v Book exported as DOCX file: {export_path}")
        
        else:
            if format_type not in ["txt", "markdown", "pdf", "epub", "docx"]:
                return log_message(f"Export format '{format_type}' not supported.")
            else:
                # Format is supported but library is not available
                missing_lib = {
                    "pdf": "reportlab",
                    "epub": "ebooklib",
                    "docx": "python-docx"
                }.get(format_type)
                
                return log_message(f"Export to {format_type} requires the {missing_lib} library. Please install it with pip.")
    
    except Exception as e:
        error_msg = f"Error exporting book: {str(e)}"
        return log_message(error_msg)

def get_current_book_info():
    """Get information about the current book project"""
    if not current_book_folder:
        return "No active book project."
    
    try:
        info = f"# Current Book: {current_book_title}\n\n"
        info += f"Project folder: {current_book_folder}\n\n"
        
        # Series info
        if current_book_data.get("series_id"):
            with closing(sqlite3.connect('book_projects.db')) as conn:
                with closing(conn.cursor()) as cursor:
                    cursor.execute("SELECT name FROM series WHERE id = ?", (current_book_data["series_id"],))
                    result = cursor.fetchone()
                    if result:
                        series_name = result[0]
                        info += f"## Series\nPart of the '{series_name}' series\n\n"
        
        # Book style
        if current_book_data.get("style"):
            info += f"## Style\n{current_book_data['style']}\n\n"
        
        # Target audience
        if current_book_data.get("target_audience"):
            audience = current_book_data["target_audience"]
            info += "## Target Audience\n"
            
            if "age_min" in audience and "age_max" in audience:
                info += f"- Age Range: {audience['age_min']}-{audience['age_max']} years\n"
            
            if "reading_level" in audience:
                info += f"- Reading Level: {audience['reading_level']}\n"
            
            if "accommodations" in audience and audience["accommodations"]:
                info += "- Accommodations: "
                accom_types = [accom["type"] for accom in audience["accommodations"]]
                info += ", ".join(accom_types) + "\n"
            
            info += "\n"
        
        # Characters
        if current_book_data.get("characters"):
            info += "## Characters\n"
            for name in current_book_data["characters"].keys():
                info += f"- {name}\n"
            info += "\n"
        
        # World building
        if current_book_data.get("world_building"):
            info += "## World Building\n"
            for category in current_book_data["world_building"].keys():
                info += f"- {category}\n"
            info += "\n"
        
        # Hierarchical world building
        if current_book_data.get("world_building_hierarchy"):
            info += "## World Building Hierarchy\n"
            for category, subcategories in current_book_data["world_building_hierarchy"].items():
                info += f"- {category}\n"
                for subcategory, elements in subcategories.items():
                    info += f"  - {subcategory}: {len(elements)} elements\n"
            info += "\n"
        
        # Chapter count
        if current_book_data.get("chapters"):
            info += f"## Chapters\n"
            info += f"Total chapters: {len(current_book_data['chapters'])}\n\n"
            
            # Count completed chapters
            chapter_files = [f for f in os.listdir(current_book_folder) 
                           if f.startswith("chapter_") and f.endswith(".txt")]
            info += f"Generated chapters: {len(chapter_files)}\n\n"
            
            for chapter in current_book_data["chapters"]:
                chapter_file = f"chapter_{chapter['chapter_number']:02d}.txt"
                chapter_status = "v" if chapter_file in os.listdir(current_book_folder) else "□"
                info += f"{chapter_status} Chapter {chapter['chapter_number']}: {chapter['title']}\n"
        
        return info
    
    except Exception as e:
        return f"Error getting book info: {str(e)}"

# Create the Gradio interface
def create_gradio_interface():
    """Create and return the Gradio interface with improved outline generation"""
    with gr.Blocks(title="Geeky Ghost Writer", theme=gr.themes.Soft()) as app:
        gr.Markdown("# 👻 Geeky Ghost Writer")
        gr.Markdown("""This application uses Ollama to generate books based on your prompts. 
                    Make sure Ollama is running before using this application.""")
        
        # Project Management Tab
        with gr.Tab("Project Management"):
            with gr.Row():
                with gr.Column(scale=1):
                    # Create new project section
                    gr.Markdown("### Create New Project")
                    new_title_input = gr.Textbox(
                        label="Book Title", 
                        placeholder="Enter a title for your new book",
                        lines=1
                    )
                    
                    style_input = gr.Textbox(
                        label="Writing Style (Optional)", 
                        placeholder="Describe the desired writing style (e.g., 'whimsical and humorous', 'dark and gritty')",
                        lines=2
                    )
                    
                    # Add series dropdown for new project
                    series_dropdown = gr.Dropdown(
                        label="Add to Series (Optional)",
                        choices=[("No Series", "")] + get_existing_series(),
                        value="No Series"
                    )
                    
                    create_btn = gr.Button("Create New Book Project", variant="primary")
                    
                    # Horizontal divider
                    gr.Markdown("---")
                    
                    # Series management section
                    gr.Markdown("### Series Management")
                    series_name_input = gr.Textbox(
                        label="Series Name", 
                        placeholder="Enter a name for your new series",
                        lines=1
                    )
                    
                    series_desc_input = gr.Textbox(
                        label="Series Description", 
                        placeholder="Describe your series",
                        lines=3
                    )
                    
                    create_series_btn = gr.Button("Create New Series", variant="primary")
                    
                    # Horizontal divider
                    gr.Markdown("---")
                    
                    # Load existing project section
                    gr.Markdown("### Load Existing Project")
                    
                    project_dropdown = gr.Dropdown(
                        label="Select a project to load",
                        choices=[("Select a project", "")] + get_existing_projects(),
                        value="Select a project",
                        allow_custom_value=True  # Fix for the warning about values not in list
                    )
                    
                    load_btn = gr.Button("Load Selected Project")
                    refresh_btn = gr.Button("Refresh Project List")
                
                with gr.Column(scale=2):
                    # Current book info
                    current_book_info = gr.Markdown(label="Current Book Information")
                    project_log = gr.Markdown(label="Project Log")
                    
                    # Add to Series section (for existing projects)
                    with gr.Accordion("Add Current Book to Series", open=False):
                        add_to_series_dropdown = gr.Dropdown(
                            label="Select Series",
                            choices=[("Select a series", "")] + get_existing_series(),
                            value="Select a series"
                        )
                        add_to_series_btn = gr.Button("Add to Selected Series", variant="primary")
        
        # Target Audience Tab
        with gr.Tab("Target Audience"):
            with gr.Row():
                with gr.Column(scale=1):
                    # Age range
                    gr.Markdown("### Age Range & Reading Level")
                    
                    with gr.Row():
                        age_min_input = gr.Number(
                            label="Minimum Age",
                            value=0,
                            minimum=0,
                            maximum=100,
                            step=1
                        )
                        
                        age_max_input = gr.Number(
                            label="Maximum Age",
                            value=99,
                            minimum=0,
                            maximum=100,
                            step=1
                        )
                    
                    reading_level_input = gr.Dropdown(
                        label="Reading Level",
                        choices=["Early Reader", "Children", "Middle Grade", "Young Adult", "Adult", "General"],
                        value="General"
                    )
                    
                    set_audience_btn = gr.Button("Set Age Range & Reading Level", variant="primary")
                    
                    # Neurodivergent accommodations
                    gr.Markdown("### Neurodivergent Accommodations")
                    
                    accom_type_input = gr.Dropdown(
                        label="Accommodation Type",
                        choices=[
                            "ADHD", "Autism", "Dyslexia", "Language Processing", 
                            "Visual Processing", "Sensory Sensitivity", "Other"
                        ],
                        value="ADHD"
                    )
                    
                    accom_desc_input = gr.Textbox(
                        label="Accommodation Description",
                        placeholder="Describe how to accommodate this neurodivergence in the writing",
                        lines=4
                    )
                    
                    add_accom_btn = gr.Button("Add Accommodation", variant="primary")
                    
                    # Content guidelines
                    gr.Markdown("### Content Guidelines")
                    
                    guideline_input = gr.Textbox(
                        label="Content Guideline",
                        placeholder="Add a content guideline (e.g., 'Avoid graphic violence', 'Include diverse representation')",
                        lines=2
                    )
                    
                    add_guideline_btn = gr.Button("Add Guideline", variant="primary")
                
                with gr.Column(scale=2):
                    # Target audience display
                    audience_display = gr.Markdown(label="Target Audience")
                    audience_log = gr.Markdown(label="Action Log")
        
        # World Building & Characters Tab
        with gr.Tab("World Building & Characters"):
            with gr.TabItem("Basic World Building"):
                with gr.Row():
                    with gr.Column(scale=1):
                        # World building section
                        gr.Markdown("### Add World Building Element")
                        wb_category = gr.Textbox(
                            label="Category", 
                            placeholder="e.g., Geography, Magic System, Technology",
                            lines=1
                        )
                        wb_content = gr.Textbox(
                            label="Description", 
                            placeholder="Describe this aspect of your world",
                            lines=6
                        )
                        wb_add_btn = gr.Button("Add World Building Element", variant="primary")
                        
                        # World building edit/delete section
                        gr.Markdown("### Edit/Delete World Building Element")
                        wb_select = gr.Dropdown(
                            label="Select Element",
                            choices=get_world_building_categories(),
                            value="Select a category"
                        )
                        
                        # Get content button
                        wb_load_btn = gr.Button("Load Content")
                        
                        # Edit content field
                        wb_edit_content = gr.Textbox(
                            label="Edit Description",
                            lines=6
                        )
                        
                        # Action buttons
                        with gr.Row():
                            wb_save_btn = gr.Button("Save Changes", variant="primary")
                            wb_delete_btn = gr.Button("Delete Element", variant="stop")
                    
                    with gr.Column(scale=2):
                        # Display world building
                        wb_display = gr.Markdown(label="World Building Information")
                        
                        # Delete confirmation
                        with gr.Group(visible=False) as delete_confirm_group:
                            delete_confirm_text = gr.Markdown("Are you sure you want to delete this item?")
                            with gr.Row():
                                delete_confirm_btn = gr.Button("Yes, Delete", variant="stop")
                                delete_cancel_btn = gr.Button("Cancel", variant="secondary")

                        # Hidden storage for delete operation
                        delete_type = gr.Textbox(visible=False)  
                        delete_name = gr.Textbox(visible=False)  
                        delete_wb_category = gr.Textbox(visible=False)
                        delete_wb_subcategory = gr.Textbox(visible=False)
                        delete_wb_name = gr.Textbox(visible=False)
                    
                    with gr.Column(scale=1):
                        # Hierarchical world building section
                        gr.Markdown("### Add Hierarchical World Building Element")
                        
                        wb_hier_category = gr.Textbox(
                            label="Category", 
                            placeholder="e.g., Geography, Magic System, Technology",
                            lines=1
                        )
                        
                        wb_hier_subcategory = gr.Textbox(
                            label="Subcategory", 
                            placeholder="e.g., Mountains, Spells, Devices",
                            lines=1
                        )
                        
                        wb_hier_name = gr.Textbox(
                            label="Element Name", 
                            placeholder="e.g., Mt. Olympus, Fireball, Teleporter",
                            lines=1
                        )
                        
                        wb_hier_content = gr.Textbox(
                            label="Description", 
                            placeholder="Describe this element of your world",
                            lines=6
                        )
                        
                        wb_hier_add_btn = gr.Button("Add Hierarchical Element", variant="primary")
                        
                        # Hierarchical world building edit/delete section
                        gr.Markdown("### Edit/Delete Hierarchical Element")
                        
                        wb_hier_category_select = gr.Dropdown(
                            label="Select Category",
                            choices=get_world_building_hierarchy_categories(),
                            value="Select a category"
                        )
                        
                        wb_hier_subcategory_select = gr.Dropdown(
                            label="Select Subcategory",
                            choices=["Select a category first"],
                            value="Select a category first"
                        )
                        
                        wb_hier_element_select = gr.Dropdown(
                            label="Select Element",
                            choices=["Select a subcategory first"],
                            value="Select a subcategory first"
                        )
                        
                        # Get element content button
                        wb_hier_load_btn = gr.Button("Load Element")
                        
                        # Edit element content field
                        wb_hier_edit_content = gr.Textbox(
                            label="Edit Description",
                            lines=6
                        )
                        
                        # Action buttons
                        with gr.Row():
                            wb_hier_save_btn = gr.Button("Save Changes", variant="primary")
                            wb_hier_delete_btn = gr.Button("Delete Element", variant="stop")
                    
                    with gr.Column(scale=2):
                        # Display hierarchical world building
                        wb_hier_display = gr.Markdown(label="Hierarchical World Building")
            
            with gr.TabItem("Characters"):
                with gr.Row():
                    with gr.Column(scale=1):
                        # Character section
                        gr.Markdown("### Add Character")
                        char_name = gr.Textbox(
                            label="Character Name", 
                            placeholder="Character's name",
                            lines=1
                        )
                        char_desc = gr.Textbox(
                            label="Character Description", 
                            placeholder="Describe the character, their traits, background, etc.",
                            lines=6
                        )
                        char_add_btn = gr.Button("Add Character", variant="primary")
                        
                        # Character edit/delete section
                        gr.Markdown("### Edit/Delete Character")
                        char_select = gr.Dropdown(
                            label="Select Character",
                            choices=get_character_names(),
                            value="Select a character"
                        )
                        
                        # Get character button
                        char_load_btn = gr.Button("Load Character")
                        
                        # Edit character field
                        char_edit_desc = gr.Textbox(
                            label="Edit Description",
                            lines=6
                        )
                        
                        # Action buttons
                        with gr.Row():
                            char_save_btn = gr.Button("Save Changes", variant="primary")
                            char_delete_btn = gr.Button("Delete Character", variant="stop")
                    
                    with gr.Column(scale=2):
                        # Display characters
                        char_display = gr.Markdown(label="Characters")
            
            with gr.TabItem("Character Relationships"):
                with gr.Row():
                    with gr.Column(scale=1):
                        # Character relationships section
                        gr.Markdown("### Add Character Relationship")
                        
                        char1_select = gr.Dropdown(
                            label="Character 1",
                            choices=get_character_names(),
                            value="Select a character"
                        )
                        
                        char2_select = gr.Dropdown(
                            label="Character 2",
                            choices=get_character_names(),
                            value="Select a character"
                        )
                        
                        relationship_type = gr.Dropdown(
                            label="Relationship Type",
                            choices=[
                                "Family", "Friends", "Allies", "Rivals", "Enemies", 
                                "Lovers", "Teacher/Student", "Employer/Employee", "Other"
                            ],
                            value="Friends"
                        )
                        
                        relationship_desc = gr.Textbox(
                            label="Relationship Description", 
                            placeholder="Describe the relationship between these characters",
                            lines=6
                        )
                        
                        add_relationship_btn = gr.Button("Add Relationship", variant="primary")
                    
                    with gr.Column(scale=2):
                        # Display character relationships
                        relationships_display = gr.Markdown(label="Character Relationships")
            
            with gr.TabItem("Character Arcs"):
                with gr.Row():
                    with gr.Column(scale=1):
                        # Character arcs section
                        gr.Markdown("### Add Character Development Arc")
                        
                        arc_char_select = gr.Dropdown(
                            label="Select Character",
                            choices=get_character_names(),
                            value="Select a character"
                        )
                        
                        arc_points = gr.Textbox(
                            label="Character Arc Points", 
                            placeholder="Describe the character's development arc throughout the story. Each line will be treated as a separate arc point.",
                            lines=8
                        )
                        
                        add_arc_btn = gr.Button("Add Character Arc", variant="primary")
                    
                    with gr.Column(scale=2):
                        # Display character arcs
                        arcs_display = gr.Markdown(label="Character Development Arcs")
            
            with gr.TabItem("Flowchart Input"):
                with gr.Row():
                    with gr.Column(scale=1):
                        # Flowchart input section
                        gr.Markdown("### Flowchart Input")
                        gr.Markdown("""
                        This tool allows you to input a flowchart-like structure and have it automatically organized into the appropriate categories.
                        
                        Format your input as follows:
                        
                        ```
                        NODE: [Type]: [Name]
                        [Content]
                        END_NODE
                        
                        CONNECTION: [Source Node ID] -> [Target Node ID]
                        [Relationship Description]
                        END_CONNECTION
                        ```
                        
                        Types can be: Character, World, Plot, Setting
                        """)
                        
                        flowchart_input = gr.Textbox(
                            label="Flowchart Input", 
                            placeholder="Paste your flowchart data here...",
                            lines=15
                        )
                        
                        process_flowchart_btn = gr.Button("Process Flowchart", variant="primary")
                    
                    with gr.Column(scale=2):
                        # Display processing results
                        flowchart_output = gr.Markdown(label="Processing Results")
        
        # Book Generation Tab
        with gr.Tab("Book Generation"):
            with gr.Row():
                with gr.Column(scale=2):
                    # Input section
                    prompt_input = gr.Textbox(
                        label="Story Prompt", 
                        placeholder="Enter your story idea, characters, setting, etc.",
                        lines=8
                    )
                    
                    with gr.Row():
                        chapters_input = gr.Slider(
                            label="Number of Chapters",
                            minimum=1,
                            maximum=30,
                            step=1,
                            value=5
                        )
                        
                        models_dropdown = gr.Dropdown(
                            label="Ollama Model",
                            choices=get_ollama_models(),
                            value="mistral"
                        )
                    
                    with gr.Row():
                        outline_btn = gr.Button("Generate Outline", variant="primary")
                        book_btn = gr.Button("Generate All Chapters", variant="primary")
                        stop_btn = gr.Button("Stop Generation", variant="stop")
                        combine_btn = gr.Button("Combine Chapters", variant="secondary")
                    
                    # Selective chapter generation section
                    with gr.Accordion("Selective Chapter Generation", open=False):
                        chapter_selection = gr.CheckboxGroup(
                            label="Select Chapters to Generate",
                            choices=[],
                            value=[]
                        )
                        
                        generate_selected_btn = gr.Button("Generate Selected Chapters", variant="primary")
                    
                    # Add outline revision section
                    with gr.Accordion("Outline Revision", open=False):
                        gr.Markdown(
                            """
                            ### Revise Specific Chapters
                            Use this section to revise specific chapters of your outline.
                            Provide feedback for how you want to change the chapter.
                            """
                        )
                        
                        chapter_to_revise = gr.Number(
                            label="Chapter Number to Revise",
                            value=1,
                            minimum=1,
                            step=1
                        )
                        
                        revision_feedback = gr.Textbox(
                            label="Revision Feedback",
                            placeholder="Describe how you want to revise this chapter (e.g., 'Make it more action-oriented', 'Change the setting to a forest', etc.)",
                            lines=3
                        )
                        
                        revise_btn = gr.Button("Revise Chapter", variant="primary")
                
                with gr.Column(scale=3):
                    # Output section
                    outline_output = gr.Markdown(label="Generated Outline")
                    log_output = gr.Markdown(label="Generation Log")
                    
                    # Detailed progress display
                    progress_display = gr.Markdown(label="Generation Progress")
                    
                    # Add refresh button for manual progress updates
                    refresh_progress_btn = gr.Button("Refresh Progress")
        
        # Editor Tab
        with gr.Tab("Editor"):
            with gr.Row():
                with gr.Column(scale=1):
                    # Chapter selection
                    chapter_select = gr.Number(
                        label="Chapter Number",
                        value=1,
                        minimum=1,
                        step=1
                    )
                    load_chapter_btn = gr.Button("Load Chapter")
                    
                    # Find and replace
                    gr.Markdown("### Find and Replace")
                    find_text = gr.Textbox(
                        label="Find", 
                        placeholder="Text to find",
                        lines=1
                    )
                    replace_text = gr.Textbox(
                        label="Replace with", 
                        placeholder="Text to replace with",
                        lines=1
                    )
                    replace_btn = gr.Button("Find and Replace", variant="primary")
                    
                    # Section deletion and rewriting
                    gr.Markdown("### Section Management")
                    section_start = gr.Number(
                        label="Section Start Line",
                        value=1,
                        minimum=1,
                        step=1
                    )
                    section_end = gr.Number(
                        label="Section End Line",
                        value=10,
                        minimum=1,
                        step=1
                    )
                    
                    with gr.Row():
                        delete_section_btn = gr.Button("Delete Section", variant="stop")
                        rewrite_section_btn = gr.Button("Rewrite Section", variant="primary")
                
                with gr.Column(scale=2):
                    # Chapter editor
                    chapter_editor = gr.TextArea(
                        label="Chapter Content", 
                        placeholder="Chapter content will appear here",
                        lines=30
                    )
                    save_chapter_btn = gr.Button("Save Changes", variant="primary")
                    editor_status = gr.Markdown(label="Editor Status")
        
        # View Results Tab
        with gr.Tab("View Results"):
            with gr.Row():
                with gr.Column(scale=1):
                    refresh_files_btn = gr.Button("Refresh File List")
                    project_files_dropdown = gr.Dropdown(
                        label="Select a file to view",
                        choices=get_project_file_options(),
                        value="Select a file"
                    )
                    
                    # Export options
                    gr.Markdown("### Export Options")
                    
                    # Create a list of available export formats
                    available_formats = ["txt", "markdown"]
                    if export_capabilities["pdf"]:
                        available_formats.append("pdf")
                    if export_capabilities["epub"]:
                        available_formats.append("epub")
                    if export_capabilities["docx"]:
                        available_formats.append("docx")
                    
                    export_format = gr.Dropdown(
                        label="Export Format",
                        choices=available_formats,
                        value="txt"
                    )
                    
                    # Show library information for missing formats
                    if not all(export_capabilities.values()):
                        missing_libs = []
                        if not export_capabilities["pdf"]:
                            missing_libs.append("reportlab (for PDF export)")
                        if not export_capabilities["epub"]:
                            missing_libs.append("ebooklib (for EPUB export)")
                        if not export_capabilities["docx"]:
                            missing_libs.append("python-docx (for DOCX export)")
                        
                        if missing_libs:
                            gr.Markdown(f"💡 Some export formats require additional libraries: {', '.join(missing_libs)}")
                    
                    export_btn = gr.Button("Export Book", variant="primary")
                
                with gr.Column(scale=2):
                    files_list = gr.Markdown(label="Project Files")
                    file_content = gr.Markdown(label="File Content")
        
        # --------- Event Handlers ---------
        
        # Project Management Tab
        create_btn.click(
            create_book_project,
            inputs=[new_title_input, style_input, series_dropdown],
            outputs=[project_log]
        ).then(
            get_current_book_info,
            inputs=[],
            outputs=[current_book_info]
        )
        
        # Series creation
        create_series_btn.click(
            lambda name, desc: create_series(name, desc)[0],
            inputs=[series_name_input, series_desc_input],
            outputs=[project_log]
        ).then(
            lambda: gr.Dropdown(
                label="Add to Series (Optional)",
                choices=[("No Series", "")] + get_existing_series(),
                value="No Series"
            ),
            inputs=None,
            outputs=[series_dropdown]
        ).then(
            lambda: gr.Dropdown(
                label="Select Series",
                choices=[("Select a series", "")] + get_existing_series(),
                value="Select a series"
            ),
            inputs=None,
            outputs=[add_to_series_dropdown]
        )
        
        # Add current book to series
        add_to_series_btn.click(
            lambda series_id: add_book_to_series(series_id, current_book_id) if current_book_id else "No active book project. Please create or load a book project first.",
            inputs=[add_to_series_dropdown],
            outputs=[project_log]
        ).then(
            get_current_book_info,
            inputs=[],
            outputs=[current_book_info]
        )
        
        # Load project - UPDATED to refresh all UI components
        load_btn.click(
            lambda selection: load_book_project(selection) if selection else "No project selected.",
            inputs=[project_dropdown],
            outputs=[project_log]
        ).then(
            get_current_book_info,
            inputs=[],
            outputs=[current_book_info]
        ).then(
            lambda: gr.CheckboxGroup(
                label="Select Chapters to Generate",
                choices=[f"Chapter {i+1}" for i in range(len(current_outline))] if current_outline else [],
                value=[]
            ),
            inputs=None,
            outputs=[chapter_selection]
        ).then(
            format_outline_for_display,
            inputs=[],
            outputs=[outline_output]
        ).then(
            get_world_building_display,
            inputs=[],
            outputs=[wb_display]
        ).then(
            get_world_building_hierarchy_display,
            inputs=[],
            outputs=[wb_hier_display]
        ).then(
            get_characters_display,
            inputs=[],
            outputs=[char_display]
        ).then(
            get_character_relationships_display,
            inputs=[],
            outputs=[relationships_display]
        ).then(
            get_character_arcs_display,
            inputs=[],
            outputs=[arcs_display]
        ).then(
            get_target_audience_display,
            inputs=[],
            outputs=[audience_display]
        ).then(
            lambda: refresh_wb_categories(),
            inputs=None,
            outputs=[wb_select]
        ).then(
            lambda: refresh_wb_hierarchy_categories(),
            inputs=None,
            outputs=[wb_hier_category_select]
        ).then(
            lambda: refresh_char_names(),
            inputs=None,
            outputs=[char_select]
        ).then(
            lambda: refresh_char_names(),
            inputs=None,
            outputs=[char1_select]
        ).then(
            lambda: refresh_char_names(),
            inputs=None,
            outputs=[char2_select]
        ).then(
            lambda: refresh_char_names(),
            inputs=None,
            outputs=[arc_char_select]
        )
        
        # Refresh project list
        refresh_btn.click(
            fn=lambda: gr.Dropdown(
                label="Select a project to load",
                choices=[("Select a project", "")] + get_existing_projects(),
                value="Select a project",
                allow_custom_value=True  # Fix for the warning about values not in list
            ),
            inputs=None,
            outputs=[project_dropdown]
        )
        
        # Target Audience Tab
        set_audience_btn.click(
            set_target_audience,
            inputs=[age_min_input, age_max_input, reading_level_input],
            outputs=[audience_log]
        ).then(
            get_target_audience_display,
            inputs=[],
            outputs=[audience_display]
        )
        
        add_accom_btn.click(
            add_neurodivergent_accommodation,
            inputs=[accom_type_input, accom_desc_input],
            outputs=[audience_log]
        ).then(
            get_target_audience_display,
            inputs=[],
            outputs=[audience_display]
        )
        
        add_guideline_btn.click(
            add_content_guideline,
            inputs=[guideline_input],
            outputs=[audience_log]
        ).then(
            get_target_audience_display,
            inputs=[],
            outputs=[audience_display]
        )
        
        # World Building Handlers
        def refresh_wb_categories():
            return gr.Dropdown(
                label="Select Element",
                choices=get_world_building_categories(),
                value="Select a category"
            )
        
        wb_add_btn.click(
            add_world_building_entry,
            inputs=[wb_category, wb_content],
            outputs=[wb_display, project_log]
        ).then(
            get_current_book_info,
            inputs=[],
            outputs=[current_book_info]
        ).then(
            refresh_wb_categories,
            inputs=None,
            outputs=[wb_select]
        ).then(
            lambda: "",
            inputs=None,
            outputs=[wb_category]
        ).then(
            lambda: "",
            inputs=None,
            outputs=[wb_content]
        )
        
        # Load world building content
        wb_load_btn.click(
            get_world_building_content,
            inputs=[wb_select],
            outputs=[wb_edit_content]
        )
        
        # Save world building changes
        wb_save_btn.click(
            edit_world_building_entry,
            inputs=[wb_select, wb_edit_content],
            outputs=[wb_display, project_log]
        ).then(
            get_current_book_info,
            inputs=[],
            outputs=[current_book_info]
        ).then(
            lambda: "",
            inputs=None,
            outputs=[wb_edit_content]
        )
        
        # Delete world building - confirmation
        wb_delete_btn.click(
            lambda category: (gr.Group(visible=True), f"Are you sure you want to delete '{category}'?", "world_building", category),
            inputs=[wb_select],
            outputs=[delete_confirm_group, delete_confirm_text, delete_type, delete_name]
        )
        
        # Hierarchical World Building Handlers
        def refresh_wb_hierarchy_categories():
            return gr.Dropdown(
                label="Select Category",
                choices=get_world_building_hierarchy_categories(),
                value="Select a category"
            )
        
        def update_subcategory_dropdown(category):
            if category and category != "Select a category":
                return gr.Dropdown(
                    label="Select Subcategory",
                    choices=get_world_building_subcategories(category),
                    value="Select a subcategory"
                )
            else:
                return gr.Dropdown(
                    label="Select Subcategory",
                    choices=["Select a category first"],
                    value="Select a category first"
                )
        
        def update_element_dropdown(category, subcategory):
            if category and category != "Select a category" and subcategory and subcategory != "Select a subcategory":
                return gr.Dropdown(
                    label="Select Element",
                    choices=get_world_building_elements(category, subcategory),
                    value="Select an element"
                )
            else:
                return gr.Dropdown(
                    label="Select Element",
                    choices=["Select a subcategory first"],
                    value="Select a subcategory first"
                )
        
        wb_hier_add_btn.click(
            add_world_building_element,
            inputs=[wb_hier_category, wb_hier_subcategory, wb_hier_name, wb_hier_content],
            outputs=[wb_hier_display, project_log]
        ).then(
            get_current_book_info,
            inputs=[],
            outputs=[current_book_info]
        ).then(
            refresh_wb_hierarchy_categories,
            inputs=None,
            outputs=[wb_hier_category_select]
        ).then(
            lambda: "",
            inputs=None,
            outputs=[wb_hier_category]
        ).then(
            lambda: "",
            inputs=None,
            outputs=[wb_hier_subcategory]
        ).then(
            lambda: "",
            inputs=None,
            outputs=[wb_hier_name]
        ).then(
            lambda: "",
            inputs=None,
            outputs=[wb_hier_content]
        )
        
        # Update subcategory dropdown when category changes
        wb_hier_category_select.change(
            update_subcategory_dropdown,
            inputs=[wb_hier_category_select],
            outputs=[wb_hier_subcategory_select]
        ).then(
            lambda: gr.Dropdown(
                label="Select Element",
                choices=["Select a subcategory first"],
                value="Select a subcategory first"
            ),
            inputs=None,
            outputs=[wb_hier_element_select]
        )
        
        # Update element dropdown when subcategory changes
        wb_hier_subcategory_select.change(
            update_element_dropdown,
            inputs=[wb_hier_category_select, wb_hier_subcategory_select],
            outputs=[wb_hier_element_select]
        )
        
        # Load hierarchical element content
        wb_hier_load_btn.click(
            get_world_building_element_content,
            inputs=[wb_hier_category_select, wb_hier_subcategory_select, wb_hier_element_select],
            outputs=[wb_hier_edit_content]
        )
        
        # Save hierarchical element changes
        wb_hier_save_btn.click(
            edit_world_building_element,
            inputs=[wb_hier_category_select, wb_hier_subcategory_select, wb_hier_element_select, wb_hier_edit_content],
            outputs=[wb_hier_display, project_log]
        ).then(
            lambda: "",
            inputs=None,
            outputs=[wb_hier_edit_content]
        )
        
        # Delete hierarchical element - confirmation
        wb_hier_delete_btn.click(
            lambda category, subcategory, name: (
                gr.Group(visible=True), 
                f"Are you sure you want to delete '{category}/{subcategory}/{name}'?", 
                "world_building_hierarchy",
                category,
                subcategory,
                name
            ),
            inputs=[wb_hier_category_select, wb_hier_subcategory_select, wb_hier_element_select],
            outputs=[
                delete_confirm_group, 
                delete_confirm_text, 
                delete_type, 
                delete_wb_category,
                delete_wb_subcategory,
                delete_wb_name
            ]
        )
        
        # Character Handlers
        def refresh_char_names():
            return gr.Dropdown(
                label="Select Character",
                choices=get_character_names(),
                value="Select a character"
            )
        
        char_add_btn.click(
            add_character,
            inputs=[char_name, char_desc],
            outputs=[char_display, project_log]
        ).then(
            get_current_book_info,
            inputs=[],
            outputs=[current_book_info]
        ).then(
            refresh_char_names,
            inputs=None,
            outputs=[char_select]
        ).then(
            refresh_char_names,
            inputs=None,
            outputs=[char1_select]
        ).then(
            refresh_char_names,
            inputs=None,
            outputs=[char2_select]
        ).then(
            refresh_char_names,
            inputs=None,
            outputs=[arc_char_select]
        ).then(
            lambda: "",
            inputs=None,
            outputs=[char_name]
        ).then(
            lambda: "",
            inputs=None,
            outputs=[char_desc]
        )
        
        # Load character content
        char_load_btn.click(
            get_character_description,
            inputs=[char_select],
            outputs=[char_edit_desc]
        )
        
        # Save character changes
        char_save_btn.click(
            edit_character,
            inputs=[char_select, char_edit_desc],
            outputs=[char_display, project_log]
        ).then(
            get_current_book_info,
            inputs=[],
            outputs=[current_book_info]
        ).then(
            lambda: "",
            inputs=None,
            outputs=[char_edit_desc]
        )
        
        # Delete character - confirmation
        char_delete_btn.click(
            lambda name: (gr.Group(visible=True), f"Are you sure you want to delete character '{name}'?", "character", name),
            inputs=[char_select],
            outputs=[delete_confirm_group, delete_confirm_text, delete_type, delete_name]
        )
        
        # Character Relationship Handlers
        add_relationship_btn.click(
            add_character_relationship,
            inputs=[char1_select, char2_select, relationship_type, relationship_desc],
            outputs=[relationships_display, project_log]
        ).then(
            lambda: "",
            inputs=None,
            outputs=[relationship_desc]
        )
        
        # Character Arc Handlers
        add_arc_btn.click(
            add_character_arc,
            inputs=[arc_char_select, arc_points],
            outputs=[arcs_display, project_log]
        ).then(
            lambda: "",
            inputs=None,
            outputs=[arc_points]
        )
        
        # Flowchart Input Handlers
        def parse_flowchart_input(text):
            """Parse the flowchart input text into nodes and connections"""
            try:
                # Split the input text into lines
                lines = text.split('\n')
                
                nodes = []
                connections = []
                
                i = 0
                while i < len(lines):
                    line = lines[i].strip()
                    
                    if line.startswith("NODE:"):
                        # Extract node info
                        node_info = line[5:].strip()
                        node_content = []
                        
                        i += 1
                        while i < len(lines) and not lines[i].strip() == "END_NODE":
                            node_content.append(lines[i])
                            i += 1
                        
                        nodes.append({
                            "info": node_info,
                            "content": "\n".join(node_content)
                        })
                    
                    elif line.startswith("CONNECTION:"):
                        # Extract connection info
                        connection_info = line[11:].strip()
                        connection_content = []
                        
                        i += 1
                        while i < len(lines) and not lines[i].strip() == "END_CONNECTION":
                            connection_content.append(lines[i])
                            i += 1
                        
                        connections.append({
                            "info": connection_info,
                            "content": "\n".join(connection_content)
                        })
                    
                    i += 1
                
                return {
                    "nodes": nodes,
                    "connections": connections
                }
            
            except Exception as e:
                print(f"Error parsing flowchart input: {str(e)}")
                return {
                    "nodes": [],
                    "connections": []
                }
        
        process_flowchart_btn.click(
            lambda text: process_flowchart_input(parse_flowchart_input(text)),
            inputs=[flowchart_input],
            outputs=[flowchart_output]
        ).then(
            get_current_book_info,
            inputs=[],
            outputs=[current_book_info]
        ).then(
            get_world_building_display,
            inputs=[],
            outputs=[wb_display]
        ).then(
            get_world_building_hierarchy_display,
            inputs=[],
            outputs=[wb_hier_display]
        ).then(
            get_characters_display,
            inputs=[],
            outputs=[char_display]
        )
        
        # Shared delete handlers
        def handle_delete_confirm(delete_type, name, wb_category=None, wb_subcategory=None, wb_name=None):
            """Handle delete confirmation"""
            if delete_type == "world_building":
                wb_html, log = delete_world_building_entry(name)
                return gr.Group(visible=False), "", "", wb_html, log
            elif delete_type == "character":
                char_html, log = delete_character(name)
                return gr.Group(visible=False), "", "", char_html, log
            elif delete_type == "world_building_hierarchy":
                wb_hier_html, log = delete_world_building_element(wb_category, wb_subcategory, wb_name)
                return gr.Group(visible=False), "", "", wb_hier_html, log
            return gr.Group(visible=False), "", "", "", "Unknown delete type"
        
        delete_confirm_btn.click(
            handle_delete_confirm,
            inputs=[delete_type, delete_name, delete_wb_category, delete_wb_subcategory, delete_wb_name],
            outputs=[delete_confirm_group, delete_type, delete_name, wb_display, project_log]
        ).then(
            get_current_book_info,
            inputs=[],
            outputs=[current_book_info]
        ).then(
            refresh_wb_categories,
            inputs=None,
            outputs=[wb_select]
        ).then(
            refresh_wb_hierarchy_categories,
            inputs=None,
            outputs=[wb_hier_category_select]
        ).then(
            refresh_char_names,
            inputs=None,
            outputs=[char_select]
        ).then(
            refresh_char_names,
            inputs=None,
            outputs=[char1_select]
        ).then(
            refresh_char_names,
            inputs=None,
            outputs=[char2_select]
        ).then(
            refresh_char_names,
            inputs=None,
            outputs=[arc_char_select]
        ).then(
            get_characters_display,
            inputs=None,
            outputs=[char_display]
        ).then(
            get_world_building_hierarchy_display,
            inputs=None,
            outputs=[wb_hier_display]
        )
        
        delete_cancel_btn.click(
            lambda: (gr.Group(visible=False), "", "", "", "", ""),
            inputs=None,
            outputs=[
                delete_confirm_group, 
                delete_type, 
                delete_name, 
                delete_wb_category,
                delete_wb_subcategory,
                delete_wb_name
            ]
        )
        
        # Book generation tab
        outline_btn.click(
            lambda prompt, num_chapters, model, style: generate_outline(
                f"A comprehensive book about {current_book_title}: {prompt}" if current_book_title and current_book_title.lower() not in prompt.lower() else prompt,
                num_chapters, 
                model, 
                style
            ),
            inputs=[prompt_input, chapters_input, models_dropdown, style_input],
            outputs=[outline_output, log_output]
        ).then(
            get_current_book_info,
            inputs=[],
            outputs=[current_book_info]
        ).then(
            lambda: gr.CheckboxGroup(
                label="Select Chapters to Generate",
                choices=[f"Chapter {i+1}" for i in range(len(current_outline))] if current_outline else [],
                value=[]
            ),
            inputs=None,
            outputs=[chapter_selection]
        )
        
        # Add the event handler for chapter revision
        revise_btn.click(
            revise_chapter_outline,
            inputs=[chapter_to_revise, revision_feedback, models_dropdown],
            outputs=[outline_output, log_output]
        )
        
        # Progress update functions
        def update_generation_status():
            """Update the generation status display"""
            if generation_active:
                return update_progress_info()
            else:
                return "No generation in progress."
        
        refresh_progress_btn.click(
            update_generation_status,
            inputs=None,
            outputs=[progress_display]
        )
        
        book_btn.click(
            start_book_generation, 
            inputs=[models_dropdown],
            outputs=[log_output]
        ).then(
            update_generation_status,  # Update initially
            inputs=None,
            outputs=[progress_display]
        )
        
        generate_selected_btn.click(
            lambda chapters, model_name: start_selected_chapter_generation(
                [int(ch.split()[1]) for ch in chapters],
                model_name
            ),
            inputs=[chapter_selection, models_dropdown],
            outputs=[log_output]
        )
        
        stop_btn.click(
            stop_generation,
            inputs=None,
            outputs=[log_output]
        ).then(
            update_generation_status,  # Update after stopping
            inputs=None,
            outputs=[progress_display]
        )
        
        combine_btn.click(
            combine_book,
            inputs=None,
            outputs=[log_output]
        ).then(
            update_generation_status,
            inputs=None,
            outputs=[progress_display]
        )
        
        # Editor tab
        load_chapter_btn.click(
            get_chapter_content,
            inputs=[chapter_select],
            outputs=[chapter_editor]
        )
        
        save_chapter_btn.click(
            update_chapter_content,
            inputs=[chapter_select, chapter_editor],
            outputs=[editor_status]
        )
        
        replace_btn.click(
            find_and_replace,
            inputs=[find_text, replace_text],
            outputs=[editor_status]
        ).then(
            lambda chapter_num: get_chapter_content(chapter_num) if chapter_num else "",
            inputs=[chapter_select],
            outputs=[chapter_editor]
        )
        
        # Section deletion and rewriting
        def delete_section_from_editor(editor_content, start_line, end_line):
            """Delete a section from the editor content"""
            try:
                if not editor_content:
                    return editor_content, "No content to delete from."
                
                lines = editor_content.split('\n')
                
                if start_line < 1:
                    start_line = 1
                
                if end_line > len(lines):
                    end_line = len(lines)
                
                if start_line > end_line:
                    return editor_content, "Start line must be less than or equal to end line."
                
                # Delete the specified lines
                new_lines = lines[:start_line-1] + lines[end_line:]
                new_content = '\n'.join(new_lines)
                
                return new_content, f"Deleted lines {start_line} to {end_line}."
            
            except Exception as e:
                return editor_content, f"Error deleting section: {str(e)}"
        
        delete_section_btn.click(
            delete_section_from_editor,
            inputs=[chapter_editor, section_start, section_end],
            outputs=[chapter_editor, editor_status]
        )
        
        def rewrite_section(editor_content, start_line, end_line, model_name):
            """Rewrite a section of the chapter using the model"""
            try:
                if not editor_content:
                    return editor_content, "No content to rewrite."
                
                lines = editor_content.split('\n')
                
                if start_line < 1:
                    start_line = 1
                
                if end_line > len(lines):
                    end_line = len(lines)
                
                if start_line > end_line:
                    return editor_content, "Start line must be less than or equal to end line."
                
                # Extract the section to rewrite
                section_to_rewrite = '\n'.join(lines[start_line-1:end_line])
                
                # Create the prompt for rewriting
                rewrite_prompt = f"""
                Rewrite the following section of text, maintaining the same information and tone but improving the quality:
                
                {section_to_rewrite}
                
                The rewritten text should be approximately the same length and maintain all key information.
                Focus on improving clarity, flow, and engagement, while keeping the same style and voice.
                """
                
                # Generate the rewritten section
                rewritten_section = generate_text(model_name, rewrite_prompt)
                
                # Replace the section in the original content
                new_lines = lines[:start_line-1] + rewritten_section.split('\n') + lines[end_line:]
                new_content = '\n'.join(new_lines)
                
                return new_content, f"Rewrote lines {start_line} to {end_line}."
            
            except Exception as e:
                return editor_content, f"Error rewriting section: {str(e)}"
        
        rewrite_section_btn.click(
            lambda content, start, end: rewrite_section(content, start, end, models_dropdown.value),
            inputs=[chapter_editor, section_start, section_end],
            outputs=[chapter_editor, editor_status]
        )
        
        # View Results tab
        def refresh_files_list():
            """Refresh file list dropdown"""
            return gr.Dropdown(
                label="Select a file to view",
                choices=get_project_file_options(),
                value="Select a file"
            ), list_project_files()
        
        refresh_files_btn.click(
            fn=refresh_files_list,
            inputs=None,
            outputs=[project_files_dropdown, files_list]
        )
        
        project_files_dropdown.change(
            load_project_file_content,
            inputs=[project_files_dropdown],
            outputs=[file_content]
        )
        
        export_btn.click(
            export_book_project,
            inputs=[export_format],
            outputs=[project_log]
        )
        
        # Initial display loading
        app.load(
            lambda: (
                get_world_building_display(), 
                get_characters_display(),
                get_world_building_hierarchy_display(),
                get_character_relationships_display(),
                get_character_arcs_display(),
                get_target_audience_display()
            ),
            inputs=None,
            outputs=[
                wb_display, 
                char_display, 
                wb_hier_display, 
                relationships_display, 
                arcs_display,
                audience_display
            ]
        )
    
    return app

# Initialize database when the script starts
initialize_database()

# Main entry point
if __name__ == "__main__":
    # Display startup message
    logger.info("Starting Geeky Ghost Writer...")
    logger.info("Make sure Ollama is running on http://localhost:11434")
    
    # Check Ollama connection
    if check_ollama_running():
        logger.info("Successfully connected to Ollama")
    else:
        logger.warning("Could not connect to Ollama. Make sure it's running before using the application.")
    
    # Create and launch the app
    app = create_gradio_interface()
    app.launch(share=False)
