# promptbuilder/config/schema.py
from pydantic import BaseModel, Field
from typing import List, Dict, Optional

class TabConfig(BaseModel):
    title: str = "New Project"
    directory: Optional[str] = None
    # Add other tab-specific settings if needed (e.g., last used filters)

class SnippetCategory(BaseModel):
    items: Dict[str, str] = Field(default_factory=dict) # Name -> Snippet Text

class AppConfig(BaseModel):
    tabs: List[TabConfig] = Field(default_factory=list)
    window_geometry: Optional[bytes] = None # Store QMainWindow.saveGeometry() as bytes
    window_state: Optional[bytes] = None    # Store QMainWindow.saveState() as bytes
    theme: str = "AUTO" # AUTO, LIGHT, DARK
    max_context_tokens: int = 8192 # Increased default?
    ignore_patterns: List[str] = Field(default_factory=lambda: [
        # Version control
        ".git", ".svn", ".hg",
        # IDE/Editor config
        ".idea", ".vscode", "*.sublime-project", "*.sublime-workspace", ".project", ".settings",
        # Python specific
        "__pycache__", "*.pyc", "*.pyo", "*.pyd",
        "*.egg-info", ".pytest_cache", ".mypy_cache",
        # Virtual environments
        "venv", ".venv", "env", ".env", "ENV", "VENV",
        # Build artifacts / Distribution
        "build", "dist", "node_modules", "target", "*.o", "*.so", "*.a", "*.lib", "*.dll", "*.exe",
        # OS specific
        ".DS_Store", "Thumbs.db",
        # Log files
        "*.log",
    ])
    # Store snippet definitions here or load from separate file/plugins
    prompt_snippets: Dict[str, SnippetCategory] = Field(default_factory=lambda: {
        "Objective": SnippetCategory(items={
            "Concept": "Your task is to develop a concept.",
            "Review": "Review the provided context carefully and thoroughly.",
            "Debug": "Try to debug any errors.",
            "Develop": "Implement a new feature or system.",
            "Custom": "" # Placeholder for custom input
        }),
        "Scope": SnippetCategory(items={
             "Everything": "Scope includes everything.",
             "High-level": "Scope: High-level.",
             "Low-level": "Scope: Low-level or details.",
             "Custom": ""
        }),
        "Requirements": SnippetCategory(items={
            "In-depth": "Your solution should be prepared in-depth.",
            "Superficial": "A superficial solution will suffice.",
            "High Quality": "Provide a solution of extraordinary quality.",
            "Creative": "Provide a creative, unexpected solution, not a super predictable one.",
            "Custom": ""
        }),
        "Constraints": SnippetCategory(items={
            "2 sentences": "Explain in exactly 2 sentences.",
            "2 paragraphs": "Explain in exactly 2 paragraphs.",
            "500 lines of code": "Limit to 500 lines of code.",
            "No placeholders": "Don't use placeholders, always provide the full solution.",
            "Custom": ""
        }),
        "Process": SnippetCategory(items={
            "CoT": "Chain-of-thought reasoning recommended.",
            "3 iterations": (
                "Iterate on this solution 3 times by reviewing it, "
                "finding improvements, and refining further."
            ),
            "Custom": ""
        }),
        "Output": SnippetCategory(items={
            "XML": "Use an XML-styled output format.",
            "Summary": "At the end, provide a verbose summary.",
            "Prod-ready": "Must be production-ready.",
            "Full and final": "Give me the full and final scripts you added or modified.",
            "Custom": ""
        })
    })
    common_questions: List[str] = Field(default_factory=lambda: [
        "What is one thing you would change/improve if you could and why?",
        "Is this solution lacking? What is missing?",
        "Do you see opportunities to improve the structure?"
    ])
    # Add other global settings: secrets patterns, etc.
    secret_patterns: List[str] = Field(default_factory=lambda: [
        # More specific patterns with length and character set constraints
        # Example: AWS Access Key ID (AKIA...)
        r"\b(AKIA[0-9A-Z]{16})\b",
        # Fixes high-priority issue #5: AWS Secret Key Regex Accuracy
        # Look for common assignment keywords/chars before the key
        r"(aws_secret_access_key|secret_access_key|SecretAccessKey|AWS_SECRET_ACCESS_KEY)[\s:=]+['\"]?([a-zA-Z0-9/+=]{40})['\"]?",
        # Example: Generic API Key (alphanumeric, > 20 chars) - adjust length/chars as needed
        r"api[_-]?key[\s:=]+['\"]?([a-zA-Z0-9_\-]{20,})['\"]?",
        # Example: Generic Secret (alphanumeric, > 16 chars)
        r"secret[\s:=]+['\"]?([a-zA-Z0-9_\-]{16,})['\"]?",
        # Example: Private Key Block Headers
        r"-----BEGIN (RSA|OPENSSH|EC|PGP) PRIVATE KEY-----",
    ])