import os
import openai
from prompts.ark_v5 import SYSTEM_PROMPT

def generate_resume(jd: str) -> dict:
    if not jd or len(jd.split()) < 50:
        return {"error": "JD too short — need 50+ words"}

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY environment variable is not set."}

    try:
        # Using the openai>=1.0.0 SDK client syntax
        client = openai.OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"JOB DESCRIPTION:\n{jd}"}
            ],
            temperature=0.3,
            max_tokens=3000
        )
        
        resume_text = response.choices[0].message.content
        if not resume_text:
            return {"error": "Received empty response from OpenAI."}
            
        # Clean potential markdown block formatting wrapping the plain text response
        if resume_text.startswith("```"):
            lines = resume_text.splitlines()
            if len(lines) >= 2 and lines[0].startswith("```"):
                if lines[-1].startswith("```"):
                    resume_text = "\n".join(lines[1:-1])
                else:
                    resume_text = "\n".join(lines[1:])
        
        # Calculate stats
        word_count = len(resume_text.split())
        bullet_count = sum(1 for line in resume_text.splitlines() if line.strip().startswith("- "))
        tokens_used = response.usage.total_tokens if response.usage else 0
        
        return {
            "resume": resume_text,
            "stats": {
                "words": word_count,
                "bullets": bullet_count,
                "tokens_used": tokens_used
            }
        }
    except Exception as e:
        return {"error": str(e)}
