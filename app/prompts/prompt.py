"""Prompts for AI question types in saved paragraphs API."""

# Predefined prompts for question types
SHORT_SUMMARY_PROMPT = """📝 Based on the content provided above, create a concise, well-structured summary. Format your response with:
- A brief overview (2-3 sentences)
- Key points as bullet points (•) highlighting the most important information
- Use ✅ icons sparingly for critical takeaways
- Keep the summary brief and scannable (aim for 3-5 bullet points)
- Focus on the main ideas, concepts, and important details
- Ensure the summary captures the essence of all provided content

Do NOT ask for the content - it has already been provided above as context."""

DESCRIPTIVE_NOTE_PROMPT = """📊 Based on the content provided above, create comprehensive, detailed descriptive notes. Structure your response with:
- **Overview Section**: A clear introduction explaining the main topic(s)
- **Key Concepts**: Detailed explanations of important concepts, ideas, or themes
- **Important Details**: Specific facts, data points, or noteworthy information
- **Connections**: How different sections relate to each other (if multiple sections provided)
- **Insights**: 💡 Add your analysis or insights where relevant
- Use proper markdown formatting (headers, bold, bullet points, etc.)
- Include relevant icons (📊 for data, 💡 for insights, ⚠️ for important notes) sparingly and purposefully
- Make the notes comprehensive yet well-organized and easy to navigate

Do NOT ask for the content - it has already been provided above as context."""

