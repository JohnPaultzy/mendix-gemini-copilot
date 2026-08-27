from google import genai
from google.genai import types
import config

def get_gemini_client(api_key=None):
    key = api_key if api_key else config.GEMINI_API_KEY
    if not key:
        return None
    return genai.Client(api_key=key)

def stream_chat_response(client, model_name, messages_history, system_instruction, attachments=None, attachment=None, context_info=""):
    """
    Mo-stream og tubag gikan sa Gemini nga nagsuporta sa attachments (images, .mpk text, scss, etc.).
    """
    full_system_instruction = system_instruction
    if context_info:
        full_system_instruction += f"\n\n[ADDITIONAL MENDIX CONTEXT]:\n{context_info}"

    formatted_contents = []
    for msg in messages_history:
        formatted_contents.append(
            types.Content(
                role="user" if msg["role"] == "user" else "model",
                parts=[types.Part.from_text(text=msg["content"])]
            )
        )
    
    # 1. Pundukon ang tanang attachments (list man o single)
    all_attachments = []
    if attachments:
        if isinstance(attachments, list):
            all_attachments.extend(attachments)
        else:
            all_attachments.append(attachments)
    if attachment:
        if isinstance(attachment, list):
            all_attachments.extend(attachment)
        else:
            all_attachments.append(attachment)

    # 2. I-attach sa pinakabag-ong user message
    if all_attachments and formatted_contents:
        for att in all_attachments:
            if isinstance(att, dict):
                if att.get("type") == "image":
                    formatted_contents[-1].parts.append(types.Part.from_image(att["data"]))
                elif att.get("type") == "text":
                    formatted_contents[-1].parts.append(types.Part.from_text(text=f"\n\n{att['data']}"))
            elif isinstance(att, tuple) and len(att) == 2:
                if att[0] == "image":
                    formatted_contents[-1].parts.append(types.Part.from_image(att[1]))
                elif att[0] == "text":
                    formatted_contents[-1].parts.append(types.Part.from_text(text=f"\n\n{att[1]}"))

    config_params = types.GenerateContentConfig(
        system_instruction=full_system_instruction,
        temperature=0.3,
    )

    response_stream = client.models.generate_content_stream(
        model=model_name,
        contents=formatted_contents,
        config=config_params
    )

    for chunk in response_stream:
        if chunk.text:
            yield chunk.text