"""Built-in editable templates. Using one creates a normal audited personal draft."""

CATALOG = {
    "lesson": {
        "kind": "rich_text",
        "title": "Lesson plan",
        "html": (
            "<h1>Lesson title</h1><h2>Learning objectives</h2>"
            "<ul><li>Describe what learners will be able to do.</li></ul>"
            "<h2>Explore</h2><p>Introduce the topic and examples.</p>"
            "<h2>Practice</h2><p>Add a practical activity.</p>"
            "<h2>Reflect</h2><p>How will learners apply this?</p>"
        ),
    },
    "knowledge-check": {
        "kind": "quiz",
        "title": "Knowledge check",
        "passing_score": 70,
        "questions": [
            {
                "prompt": "Replace this with your question",
                "options": ["Correct answer", "Distractor"],
                "correct": 0,
                "points": 1,
                "explanation": "Explain why the answer is correct.",
            }
        ],
    },
    "assessment": {
        "kind": "assessment",
        "title": "Competency assessment",
        "passing_score": 80,
        "questions": [
            {
                "prompt": "Describe a workplace scenario and ask for the best action.",
                "options": ["Best action", "Alternative action", "Another alternative"],
                "correct": 0,
                "points": 5,
                "explanation": "Explain the principle being assessed.",
            }
        ],
    },
}
