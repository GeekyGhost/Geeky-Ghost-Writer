# Ollama Book Generator

A Python-based application that uses Ollama with AutoGen to generate complete books through collaborative AI agents. The system employs a Gradio UI for easy interaction.

## Features

- 📚 Multi-agent collaborative writing system
- 🖥️ User-friendly Gradio interface
- 🧠 Powered by Ollama for local LLM inference
- 📝 Structured chapter generation
- 🔄 Maintains story continuity and character development
- 🌐 One-click complete book generation

## Prerequisites

- Python 3.8 or higher
- [Ollama](https://ollama.com/) installed and running
- At least one Ollama model pulled (e.g., mistral, llama2)

## Quick Start

### Windows

Simply run the `setup_and_run.bat` file, which will:
1. Check if Python is installed
2. Verify if Ollama is running
3. Create a virtual environment if needed
4. Install required dependencies
5. Launch the application

### Manual Setup

1. Create a virtual environment:
```bash
python -m venv venv
```

2. Activate the environment:
- Windows: `venv\Scripts\activate`
- Linux/Mac: `source venv/bin/activate`

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Run the application:
```bash
python app.py
```

## Usage

1. Make sure Ollama is running (visit [ollama.com](https://ollama.com/) to download)
2. Open the Gradio interface (typically at http://127.0.0.1:7860)
3. Enter your story prompt in the text area
4. Select the number of chapters and Ollama model to use
5. Click "Generate Outline" to create a detailed chapter outline
6. Click "Generate Book" to start the book generation process
7. Use "Combine Chapters" to merge all chapters into a single file

## How It Works

The system uses several specialized agents:

- **Story Planner**: Creates high-level story arcs and plot points
- **World Builder**: Establishes and maintains consistent settings
- **Memory Keeper**: Tracks continuity and context
- **Writer**: Generates the actual prose
- **Editor**: Reviews and improves content
- **Outline Creator**: Creates detailed chapter outlines

## Output

Generated content is saved in the `book_output` directory:
```
book_output/
├── outline.txt
├── chapter_01.txt
├── chapter_02.txt
└── full_book.txt
```

## Command Line Usage

You can also run the generator from the command line:

```bash
python main.py [model_name]
```

For example:
```bash
python main.py llama2
```

## Recommended Models

For best results, we recommend using one of these Ollama models:
- mistral
- mixtral
- llama2
- phi
- gemma

## Limitations

- Generation time increases with chapter count
- Quality depends on the Ollama model used
- May require significant system resources

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.