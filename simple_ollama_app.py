"""Enhanced Ollama-based book generator with project management and editing features"""
import os
import gradio as gr
import time
import requests
import json
import threading
import shutil
import re
from datetime import datetime
import uuid

# Create the base output directory
os.makedirs("book_output", exist_ok=True)

# Global variables
current_outline = None
current_book_title = None
current_book_folder = None
generation_active = False
generation_thread = None
log_messages = []
current_book_data = {
    "title": None,
    "folder": None,
    "world_building": {},
    "characters": {},
    "style": "",
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

def log_message(message):
    """Add a message to the log and return all messages"""
    log_messages.append(message)
    return "\n".join(log_messages)

def check_ollama_running():
    """Check if Ollama is running by making a request to list models"""
    try:
        response = requests.get("http://localhost:11434/api/tags")
        return response.status_code == 200
    except:
        return False

def get_ollama_models():
    """Get list of available Ollama models"""
    try:
        response = requests.get("http://localhost:11434/api/tags")
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
        print(f"Error getting Ollama models: {e}")
        return ["mistral", "llama2"]  # Default models if request fails

def generate_text(model, prompt):
    """Generate text using Ollama API directly"""
    try:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }
        
        response = requests.post(
            "http://localhost:11434/api/generate",
            json=payload
        )
        
        if response.status_code == 200:
            data = response.json()
            return data.get("response", "")
        else:
            return f"Error: {response.status_code}"
    except Exception as e:
        return f"Error: {str(e)}"

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

def create_book_project(title, style_input=""):
    """Create a new book project with the given title"""
    global current_book_title, current_book_folder, current_book_data
    
    try:
        # Sanitize the title for folder name with added uniqueness
        folder_name = sanitize_folder_name(title)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        book_folder = os.path.join("book_output", f"{folder_name}_{timestamp}")
        
        # Create the folder
        os.makedirs(book_folder, exist_ok=True)
        
        # Update current book info
        current_book_title = title
        current_book_folder = book_folder
        
        # Initialize book data structure
        current_book_data = {
            "title": title,
            "folder": book_folder,
            "created_at": timestamp,
            "style": style_input,
            "world_building": {},
            "characters": {},
            "chapters": []
        }
        
        # Save book metadata
        save_book_metadata()
        
        message = f"Created new book project: '{title}' in folder: {book_folder}"
        log_message(message)
        return message
    
    except Exception as e:
        error_msg = f"Error creating book project: {str(e)}"
        log_message(error_msg)
        return error_msg

def save_book_metadata():
    """Save book metadata to a JSON file"""
    if not current_book_folder:
        return False
    
    try:
        metadata_path = os.path.join(current_book_folder, "book_metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(current_book_data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving book metadata: {str(e)}")
        return False

def load_book_project(project_path):
    """Load an existing book project"""
    global current_book_title, current_book_folder, current_book_data, current_outline
    
    try:
        # Check if the project exists
        if not os.path.isdir(project_path):
            msg = f"Project folder does not exist: {project_path}"
            log_message(msg)
            return msg
        
        # Load metadata
        metadata_path = os.path.join(project_path, "book_metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, "r", encoding="utf-8") as f:
                current_book_data = json.load(f)
                
            # Update current book info
            current_book_title = current_book_data.get("title", "Untitled")
            current_book_folder = project_path
            
            # Load outline if available
            if current_book_data.get("chapters"):
                current_outline = current_book_data.get("chapters")
            
            msg = f"Loaded book project: '{current_book_title}'"
            log_message(msg)
            return msg
        else:
            msg = f"No metadata found for project: {project_path}"
            log_message(msg)
            return msg
    
    except Exception as e:
        error_msg = f"Error loading book project: {str(e)}"
        log_message(error_msg)
        return error_msg

def get_existing_projects():
    """Get list of existing book projects"""
    try:
        projects = []
        for item in os.listdir("book_output"):
            item_path = os.path.join("book_output", item)
            if os.path.isdir(item_path):
                metadata_path = os.path.join(item_path, "book_metadata.json")
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, "r", encoding="utf-8") as f:
                            metadata = json.load(f)
                            title = metadata.get("title", "Untitled")
                            projects.append((title, item_path))
                    except:
                        projects.append((item, item_path))
                else:
                    projects.append((item, item_path))
        
        return projects
    except Exception as e:
        print(f"Error getting existing projects: {str(e)}")
        return []

def generate_outline(initial_prompt, num_chapters, model_name, style_input=""):
    """Generate a book outline"""
    global current_outline, current_book_data
    
    # Check if we have an active book project
    if not current_book_folder:
        msg = "No active book project. Please create or load a book project first."
        log_message(msg)
        return "", msg
    
    log_message(f"Starting outline generation using {model_name} model...")
    log_message(f"Number of chapters: {num_chapters}")
    
    try:
        # Add style information if provided
        style_prompt = ""
        if style_input:
            style_prompt = f"\nThe writing style should be: {style_input}\n"
            current_book_data["style"] = style_input
        
        # Add world building info if available
        world_building_prompt = ""
        if current_book_data.get("world_building"):
            world_building_prompt = "\nWorld building information:\n"
            for key, value in current_book_data["world_building"].items():
                world_building_prompt += f"- {key}: {value}\n"
        
        # Add character info if available
        character_prompt = ""
        if current_book_data.get("characters"):
            character_prompt = "\nCharacter information:\n"
            for name, info in current_book_data["characters"].items():
                character_prompt += f"- {name}: {info}\n"
        
        # Generate a story outline using the model
        outline_prompt = f"""
        Generate a detailed {num_chapters}-chapter outline for a book based on this premise:
        
        {initial_prompt}
        {style_prompt}
        {world_building_prompt}
        {character_prompt}
        
        For each chapter, provide the following information in this exact format:
        
        Chapter 1: [Title]
        Key Events:
        - [Event 1]
        - [Event 2]
        - [Event 3]
        Character Developments: [Brief description of character developments]
        Setting: [Brief description of the setting]
        Tone: [Brief description of the emotional tone]
        
        [Repeat the above format for each chapter]
        
        Make sure each chapter has a unique title and at least 3 key events.
        Start your response with "OUTLINE:" and end with "END OF OUTLINE"
        """
        
        # Get response from Ollama using the API
        outline_text = generate_text(model_name, outline_prompt)
        
        # Process the outline into a structured format
        chapters = process_outline(outline_text, num_chapters)
        current_outline = chapters
        
        # Update book data
        current_book_data["chapters"] = chapters
        save_book_metadata()
        
        # Format the outline for display
        formatted_outline = "# Generated Book Outline\n\n"
        for chapter in chapters:
            formatted_outline += f"## Chapter {chapter['chapter_number']}: {chapter['title']}\n"
            formatted_outline += f"{chapter['prompt']}\n\n"
        
        # Save the outline to file
        outline_path = os.path.join(current_book_folder, "outline.txt")
        with open(outline_path, "w") as f:
            for chapter in chapters:
                f.write(f"\nChapter {chapter['chapter_number']}: {chapter['title']}\n")
                f.write("-" * 50 + "\n")
                f.write(chapter['prompt'] + "\n")
        
        msg = f"✓ Outline generation complete! Saved to {outline_path}"
        log_message(msg)
        return formatted_outline, msg
    
    except Exception as e:
        error_msg = f"Error generating outline: {str(e)}"
        log_message(error_msg)
        return "", error_msg

def process_outline(outline_text, num_chapters):
    """Process outline text into structured chapters"""
    import re
    
    # Extract the outline content between markers
    if "OUTLINE:" in outline_text:
        start_idx = outline_text.find("OUTLINE:")
        end_idx = outline_text.find("END OF OUTLINE")
        if end_idx == -1:
            end_idx = len(outline_text)
        outline_content = outline_text[start_idx:end_idx].strip()
    else:
        outline_content = outline_text
    
    # Split by chapter headers
    chapter_sections = re.split(r'Chapter \d+:', outline_content)
    
    chapters = []
    for i, section in enumerate(chapter_sections[1:], 1):  # Skip first empty section
        try:
            # Extract title
            title_match = re.search(r'^\s*(.+?)(?=\n|$)', section)
            title = title_match.group(1).strip() if title_match else f"Chapter {i}"
            
            # Extract key events, character developments, setting, tone
            events_match = re.search(r'Key Events:(.+?)(?=Character Developments:|$)', section, re.DOTALL)
            character_match = re.search(r'Character Developments:(.+?)(?=Setting:|$)', section, re.DOTALL)
            setting_match = re.search(r'Setting:(.+?)(?=Tone:|$)', section, re.DOTALL)
            tone_match = re.search(r'Tone:(.+?)(?=Chapter \d+:|$)', section, re.DOTALL)
            
            # Extract content for each section or use placeholders
            events = events_match.group(1).strip() if events_match else "- Event 1\n- Event 2\n- Event 3"
            character = character_match.group(1).strip() if character_match else "Character development continues"
            setting = setting_match.group(1).strip() if setting_match else "Setting for this chapter"
            tone = tone_match.group(1).strip() if tone_match else "Tone for this chapter"
            
            # Format chapter info
            chapter_info = {
                "chapter_number": i,
                "title": title,
                "prompt": "\n".join([
                    f"- Key Events: {events}",
                    f"- Character Developments: {character}",
                    f"- Setting: {setting}",
                    f"- Tone: {tone}"
                ])
            }
            
            chapters.append(chapter_info)
            
        except Exception as e:
            print(f"Error processing Chapter {i}: {str(e)}")
            # Add a minimal placeholder chapter
            chapters.append({
                "chapter_number": i,
                "title": f"Chapter {i}",
                "prompt": "- Key Events:\n- Event 1\n- Event 2\n- Event 3\n- Character Developments: Character development continues\n- Setting: Setting for this chapter\n- Tone: Tone for this chapter"
            })
    
    # Ensure we have the requested number of chapters
    while len(chapters) < num_chapters:
        next_num = len(chapters) + 1
        chapters.append({
            "chapter_number": next_num,
            "title": f"Chapter {next_num}",
            "prompt": "- Key Events:\n- Event 1\n- Event 2\n- Event 3\n- Character Developments: Character development continues\n- Setting: Setting for this chapter\n- Tone: Tone for this chapter"
        })
    
    # Trim extra chapters
    if len(chapters) > num_chapters:
        chapters = chapters[:num_chapters]
    
    # Ensure proper chapter numbering
    for i, chapter in enumerate(chapters, 1):
        chapter["chapter_number"] = i
    
    return chapters

def generate_chapter(chapter_number, chapter_info, model_name):
    """Generate a single chapter using Ollama"""
    try:
        # Check if we have an active book project
        if not current_book_folder:
            return "No active book project. Please create or load a book project first."
        
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
        
        # Add character info if available
        character_prompt = ""
        if current_book_data.get("characters"):
            character_prompt = "\nCharacter information:\n"
            for name, info in current_book_data["characters"].items():
                character_prompt += f"- {name}: {info}\n"
        
        chapter_prompt = f"""
        You are writing Chapter {chapter_number}: {chapter_info['title']} of a book titled "{current_book_title}".
        
        Follow these guidelines for the chapter:
        {chapter_info['prompt']}
        {style_prompt}
        {world_building_prompt}
        {character_prompt}
        
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
        
        # Generate the chapter
        chapter_content = generate_text(model_name, chapter_prompt)
        
        # Save the chapter
        save_path = os.path.join(current_book_folder, f"chapter_{chapter_number:02d}.txt")
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(f"Chapter {chapter_number}: {chapter_info['title']}\n\n")
            f.write(chapter_content)
        
        return f"✓ Chapter {chapter_number} written and saved to {save_path}"
    
    except Exception as e:
        error_msg = f"Error generating Chapter {chapter_number}: {str(e)}"
        print(error_msg)
        return error_msg

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
    """Thread function for book generation"""
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
        log_message("✓ Book generation complete!")
        
    except Exception as e:
        error_msg = f"Error generating book: {str(e)}"
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
        
        return log_message(f"✓ Book combined successfully! Saved to {full_book_path}")
    
    except Exception as e:
        return log_message(f"Error combining book: {str(e)}")

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
        
        # Format the current world building data for display
        world_data_formatted = get_world_building_display()
        
        msg = f"✓ Added world building entry: {category}"
        log_message(msg)
        return world_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error adding world building entry: {str(e)}"
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
        
        # Format the current world building data for display
        world_data_formatted = get_world_building_display()
        
        msg = f"✓ Updated world building entry: {category}"
        log_message(msg)
        return world_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error updating world building entry: {str(e)}"
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
        
        # Format the current world building data for display
        world_data_formatted = get_world_building_display()
        
        msg = f"✓ Deleted world building entry: {category}"
        log_message(msg)
        return world_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error deleting world building entry: {str(e)}"
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

def get_world_building_content(category):
    """Get the content of a specific world building category"""
    if not current_book_folder or "world_building" not in current_book_data:
        return ""
    
    if category in current_book_data["world_building"]:
        return current_book_data["world_building"][category]
    
    return ""

def get_world_building_display():
    """Format world building data for display"""
    if not current_book_folder or "world_building" not in current_book_data or not current_book_data["world_building"]:
        return "# World Building Information\n\nNo world building elements defined yet."
    
    # Format the current world building data for display
    world_data_formatted = "# World Building Information\n\n"
    for key, value in current_book_data["world_building"].items():
        world_data_formatted += f"## {key}\n{value}\n\n"
    
    return world_data_formatted

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
        
        # Format the current character data for display
        char_data_formatted = get_characters_display()
        
        msg = f"✓ Added character: {name}"
        log_message(msg)
        return char_data_formatted, msg
    
    except Exception as e:
        error_msg = f"Error adding character: {str(e)}"
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
        
        # Format the current character data for display
        char_data_formatted = get_characters_display()
        
        msg = f"✓ Updated character: {name}"
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
        
        # Save the updated metadata
        save_book_metadata()
        
        # Format the current character data for display
        char_data_formatted = get_characters_display()
        
        msg = f"✓ Deleted character: {name}"
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

def get_characters_display():
    """Format character data for display"""
    if not current_book_folder or "characters" not in current_book_data or not current_book_data["characters"]:
        return "# Characters\n\nNo characters defined yet."
    
    # Format the current character data for display
    char_data_formatted = "# Characters\n\n"
    for name, desc in current_book_data["characters"].items():
        char_data_formatted += f"## {name}\n{desc}\n\n"
    
    return char_data_formatted

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
        
        # Update world building entries
        if "world_building" in current_book_data:
            if old_text in current_book_data["world_building"]:
                current_book_data["world_building"][new_text] = current_book_data["world_building"].pop(old_text)
                metadata_updated = True
        
        # Save metadata if updated
        if metadata_updated:
            save_book_metadata()
        
        return log_message(f"✓ Replaced '{old_text}' with '{new_text}' ({total_replacements} replacements in {modified_files} files)")
    
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
        
        return log_message(f"✓ Updated Chapter {chapter_number}. Backup saved as {backup_file}")
    
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
        
        # For now, we only support TXT format
        # In the future, we could add PDF, EPUB, etc.
        if format_type == "txt":
            export_path = os.path.join(current_book_folder, f"{sanitize_folder_name(current_book_title)}.txt")
            shutil.copy2(full_book_path, export_path)
            return log_message(f"✓ Book exported as text file: {export_path}")
        else:
            return log_message(f"Export format '{format_type}' not supported yet.")
    
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
        
        # Book style
        if current_book_data.get("style"):
            info += f"## Style\n{current_book_data['style']}\n\n"
        
        # Characters
        if current_book_data.get("characters"):
            info += "## Characters\n"
            for name, desc in current_book_data["characters"].items():
                info += f"- **{name}**: {desc}\n"
            info += "\n"
        
        # World building
        if current_book_data.get("world_building"):
            info += "## World Building\n"
            for category, content in current_book_data["world_building"].items():
                info += f"- **{category}**: {content}\n"
            info += "\n"
        
        # Chapter count
        if current_book_data.get("chapters"):
            info += f"## Chapters\n"
            for chapter in current_book_data["chapters"]:
                info += f"- Chapter {chapter['chapter_number']}: {chapter['title']}\n"
        
        return info
    
    except Exception as e:
        return f"Error getting book info: {str(e)}"

# Create the Gradio interface
with gr.Blocks(title="Enhanced Ollama Book Generator", theme=gr.themes.Soft()) as app:
    gr.Markdown("# 📚 Enhanced Ollama Book Generator")
    gr.Markdown("""This application uses Ollama to generate books based on your prompts. 
                Make sure Ollama is running before using this application.""")
    
    # Project management section
    with gr.Tab("Project Management"):
        with gr.Row():
            with gr.Column(scale=1):
                # Create new project
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
                
                create_btn = gr.Button("Create New Book Project", variant="primary")
                
                # Load existing project
                gr.Markdown("### Load Existing Project")
                
                # Fixed refresh_projects function
                def refresh_projects_list():
                    projects = get_existing_projects()
                    return gr.Dropdown(
                        label="Select a project to load",
                        choices=[("Select a project", "")] + projects,
                        value="Select a project"
                    )
                
                project_dropdown = gr.Dropdown(
                    label="Select a project to load",
                    choices=[("Select a project", "")] + get_existing_projects(),
                    value="Select a project"
                )
                
                load_btn = gr.Button("Load Selected Project")
                refresh_btn = gr.Button("Refresh Project List")
            
            with gr.Column(scale=2):
                # Current book info
                current_book_info = gr.Markdown(label="Current Book Information")
                project_log = gr.Markdown(label="Project Log")
    
    # World building & characters section with simplified UI
    with gr.Tab("World Building & Characters"):
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
                # Display world building and characters
                wb_display = gr.Markdown(label="World Building Information")
                char_display = gr.Markdown(label="Characters")
                
                # Delete confirmation
                with gr.Group(visible=False) as delete_confirm_group:
                    delete_confirm_text = gr.Markdown("Are you sure you want to delete this item?")
                    with gr.Row():
                        delete_confirm_btn = gr.Button("Yes, Delete", variant="stop")
                        delete_cancel_btn = gr.Button("Cancel", variant="secondary")
                
                # Hidden storage for delete operation
                delete_type = gr.Textbox(visible=False)
                delete_name = gr.Textbox(visible=False)
    
    # Book generation section
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
                    book_btn = gr.Button("Generate Book", variant="primary")
                    stop_btn = gr.Button("Stop Generation", variant="stop")
                    combine_btn = gr.Button("Combine Chapters", variant="secondary")
            
            with gr.Column(scale=3):
                # Output section
                outline_output = gr.Markdown(label="Generated Outline")
                log_output = gr.Markdown(label="Generation Log")
                
                # Detailed progress display
                progress_display = gr.Markdown(label="Generation Progress")
                
                # Add refresh button for manual progress updates
                refresh_progress_btn = gr.Button("Refresh Progress")
    
    # Editor section
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
            
            with gr.Column(scale=2):
                # Chapter editor
                chapter_editor = gr.TextArea(
                    label="Chapter Content", 
                    placeholder="Chapter content will appear here",
                    lines=20
                )
                save_chapter_btn = gr.Button("Save Changes", variant="primary")
                editor_status = gr.Markdown(label="Editor Status")
    
    # View Results section
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
                export_format = gr.Dropdown(
                    label="Export Format",
                    choices=["txt"],
                    value="txt"
                )
                export_btn = gr.Button("Export Book", variant="primary")
            
            with gr.Column(scale=2):
                files_list = gr.Markdown(label="Project Files")
                file_content = gr.Markdown(label="File Content")

    # --------- Event Handlers ---------
    
    # Project Management tab
    create_btn.click(
        create_book_project,
        inputs=[new_title_input, style_input],
        outputs=[project_log]
    ).then(
        get_current_book_info,
        inputs=[],
        outputs=[current_book_info]
    )
    
    load_btn.click(
        lambda path: load_book_project(path) if path else "No project selected.",
        inputs=[project_dropdown],
        outputs=[project_log]
    ).then(
        get_current_book_info,
        inputs=[],
        outputs=[current_book_info]
    )
    
    # Fixed refresh button handler
    refresh_btn.click(
        fn=lambda: None,  # No-op function
        inputs=None,
        outputs=None
    ).then(
        fn=refresh_projects_list,
        inputs=None,
        outputs=project_dropdown
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

    # Character Handlers
    def refresh_char_names():
        return gr.Dropdown(
            label="Select Character",
            choices=get_character_names(),
            value="Select a character"
        )

    # The key fix for the character display issue
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

    # Shared delete handlers
    def handle_delete_confirm(delete_type, name):
        """Handle delete confirmation"""
        if delete_type == "world_building":
            wb_html, log = delete_world_building_entry(name)
            return gr.Group(visible=False), "", "", wb_html, log
        elif delete_type == "character":
            char_html, log = delete_character(name)
            return gr.Group(visible=False), "", "", char_html, log
        return gr.Group(visible=False), "", "", "", "Unknown delete type"

    delete_confirm_btn.click(
        handle_delete_confirm,
        inputs=[delete_type, delete_name],
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
        refresh_char_names,
        inputs=None,
        outputs=[char_select]
    ).then(
        get_characters_display,
        inputs=None,
        outputs=[char_display]
    )

    delete_cancel_btn.click(
        lambda: (gr.Group(visible=False), "", ""),
        inputs=None,
        outputs=[delete_confirm_group, delete_type, delete_name]
    )
    
    # Book generation tab
    outline_btn.click(
        generate_outline, 
        inputs=[prompt_input, chapters_input, models_dropdown, style_input],
        outputs=[outline_output, log_output]
    ).then(
        get_current_book_info,
        inputs=[],
        outputs=[current_book_info]
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
        lambda: (get_world_building_display(), get_characters_display()),
        inputs=None,
        outputs=[wb_display, char_display]
    )
    
    # Fixed handler for after delete confirmation that updates appropriate display
    def update_displays_after_delete(delete_type):
        """Update the appropriate display after delete confirmation"""
        if delete_type == "world_building":
            return get_world_building_display()
        elif delete_type == "character":
            return get_characters_display()
        return ""
        
    delete_confirm_btn.click(
        update_displays_after_delete,
        inputs=[delete_type],
        outputs=[char_display]
    )
    
    # Check if Ollama is running when the app starts
    if not check_ollama_running():
        log_output.update("⚠️ Warning: Ollama doesn't appear to be running. Please start Ollama before generating content.")

# Main entry point
if __name__ == "__main__":
    # Display startup message
    print("Starting Enhanced Ollama Book Generator...")
    print("Make sure Ollama is running on http://localhost:11434")
    
    # Launch the app
    app.launch(share=False)