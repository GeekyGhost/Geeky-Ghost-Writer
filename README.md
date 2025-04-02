# Geeky Ghost Writer

<img width="1182" alt="Screenshot 2025-04-02 143716" src="https://github.com/user-attachments/assets/f9930cfa-99c7-46e5-a9fe-dffd2efb1dee" />


A powerful book generation application that leverages Ollama's local LLMs to create complete books through an intuitive Gradio interface. This tool helps writers outline, generate, and edit full-length books with minimal effort.

## ✨ Features

- **📚 Complete Book Generation**: Create entire books from a single prompt with chapter-by-chapter generation
- **🧠 Local LLM Integration**: Powered by Ollama for private, local AI inference
- **🖥️ User-friendly Interface**: Intuitive Gradio UI with tabs for different aspects of book creation
- **📝 Project Management**: Create, save, and load book projects
- **🌐 World Building Tools**: Define and manage world elements for consistent storytelling
- **👤 Character Management**: Create and track characters throughout your narrative
- **✏️ Advanced Editing**: Edit individual chapters and perform find-and-replace across your book
- **🔍 Outline Generation**: Create detailed chapter outlines with key events, character developments, settings, and tone
- **📊 Progress Tracking**: Monitor book generation progress with time estimates
- **📤 Export Options**: Combine chapters and export your book in text format

## 📋 Requirements

- Python 3.8 or higher
- [Ollama](https://ollama.com/) installed and running locally
- At least one model loaded in Ollama (e.g., mistral, llama2, mixtral)
- Windows, macOS, or Linux operating system

## 🚀 Getting Started

### Windows Quick Setup

1. Download or clone this repository
2. Run `simple_setup.bat` which will:
   - Check for Python and Ollama installation
   - Create a virtual environment
   - Install required dependencies
   - Start the application

### Manual Installation

1. Ensure Python 3.8+ and Ollama are installed
2. Clone the repository:
   ```bash
   git clone https://github.com/GeekyGhost/Geeky-Ghost-Writer.git
   cd Geeky-Ghost-Writer
   ```

3. Create and activate a virtual environment:
   ```bash
   # Windows
   python -m venv venv
   venv\Scripts\activate

   # macOS/Linux
   python -m venv venv
   source venv/bin/activate
   ```

4. Install dependencies:
   ```bash
   pip install gradio>=4.0.0 requests>=2.25.0 markdown>=3.3.0 pyyaml>=6.0
   ```

5. Run the application:
   ```bash
   python simple_ollama_app.py
   ```

## 🧩 How to Use

The application interface is divided into several tabs:

### 1. Project Management
- Create new book projects with titles and writing style descriptions
- Load and manage existing projects
- View current project information

### 2. World Building & Characters
- Create detailed world elements (geography, magic systems, technology, etc.)
- Add and manage character profiles
- Edit or delete world-building elements and characters

### 3. Book Generation
- Enter your story prompt
- Select the number of chapters and Ollama model to use
- Generate a detailed chapter outline
- Generate the full book chapter by chapter
- Monitor generation progress
- Combine chapters into a complete book

### 4. Editor
- Load and edit individual chapters
- Perform find-and-replace operations across the entire book
- Save chapter changes

### 5. View Results
- Browse and view generated files
- Export your book in text format (with more formats planned for future updates)

## 💻 Advanced Usage

### Recommended Models

For best results, use one of these Ollama models:
- `mistral` (balanced performance and quality)
- `mixtral` (highest quality but slower)
- `llama2` (good all-around performance)
- `phi` (faster, lighter model)
- `gemma` (Google's efficient model)

> **💡 Model Management Tip**: For an easy way to download, manage, and configure your Ollama models, check out [Little Geeky's Learning UI](https://github.com/GeekyGhost/Little-Geeky-s-Learning-UI.git) - a companion tool that provides a user-friendly interface for Ollama model management.

### Project Structure

Generated content is saved in the `book_output` directory with this structure:
```
book_output/
├── YourBookTitle_UUID_Timestamp/
    ├── book_metadata.json
    ├── outline.txt
    ├── chapter_01.txt
    ├── chapter_02.txt
    └── full_book.txt
```

### Generation Process

The application uses a multi-step process:
1. **Project Creation**: Set up book details, world, and characters
2. **Outline Generation**: Create chapter outlines with key events
3. **Chapter Generation**: Generate each chapter based on the outline
4. **Editing**: Refine and improve content
5. **Export**: Combine chapters and export the book

## 🧰 Technical Details

The application consists of:
- Gradio-based UI with multiple interactive tabs
- Direct integration with the Ollama API for text generation
- Project management with metadata persistence
- Thread-based chapter generation to prevent UI freezing
- Progress tracking and estimation

## 📣 Limitations

- Generation time increases with chapter count
- Quality depends on the Ollama model used
- May require significant system resources for larger models
- Currently only exports to text format

## 🔮 Upcoming Features

- Additional export formats (PDF, EPUB)
- Text-to-speech integration
- Illustration generation
- Enhanced editing tools
- Custom writing styles and templates

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 🔗 Related Projects

- [Little Geeky's Learning UI](https://github.com/GeekyGhost/Little-Geeky-s-Learning-UI.git): For now, you can use this as a companion tool for managing your Ollama models with a user-friendly interface

---

*Geeky Ghost Writer - Let AI help craft your next literary masterpiece*
