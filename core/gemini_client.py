import io
from google import genai
from google.genai import types
from PIL import Image
import config

def get_gemini_client(api_key=None):
    key = api_key if api_key else config.GEMINI_API_KEY
    if not key:
        return None
    return genai.Client(api_key=key)

def pil_to_bytes(pil_image):
    buffer = io.BytesIO()
    if pil_image.mode in ("RGBA", "P"):
        pil_image = pil_image.convert("RGB")
    pil_image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()

def stream_chat_response(client, model_name, messages_history, system_instruction, attachments=None, attachment=None, context_info="", on_fallback_callback=None):
    """
    Mo-stream og tubag nga naay Seamless Failover (Kung maputol ang una,
    i-discard ang putol nga chunks aron ang fallback model makahatag og 100% kompleto nga tubag).
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

    if all_attachments and formatted_contents:
        for att in all_attachments:
            if isinstance(att, dict):
                if att.get("type") == "image":
                    img_obj = att["data"]
                    if isinstance(img_obj, Image.Image):
                        raw_bytes = pil_to_bytes(img_obj)
                    elif isinstance(img_obj, bytes):
                        raw_bytes = img_obj
                    else:
                        continue
                    formatted_contents[-1].parts.append(
                        types.Part.from_bytes(data=raw_bytes, mime_type="image/jpeg")
                    )
                elif att.get("type") == "text":
                    formatted_contents[-1].parts.append(
                        types.Part.from_text(text=f"\n\n{att['data']}")
                    )

    config_params = types.GenerateContentConfig(
        system_instruction=full_system_instruction,
        temperature=0.3,
    )

    fallback_priority = [
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash"
    ]
    models_to_try = [model_name] + [m for m in fallback_priority if m != model_name]

    for idx, current_model in enumerate(models_to_try):
        current_model_chunks = []
        try:
            if idx > 0 and on_fallback_callback:
                on_fallback_callback(models_to_try[idx-1], current_model)

            response_stream = client.models.generate_content_stream(
                model=current_model,
                contents=formatted_contents,
                config=config_params
            )
            
            for chunk in response_stream:
                if chunk.text:
                    current_model_chunks.append(chunk.text)
                    # I-tag ang chunk uban ang model index aron dali ma-reset sa app.py kung naay fallback
                    yield {"model_idx": idx, "text": chunk.text, "is_fresh_model": len(current_model_chunks) == 1}
            
            if current_model_chunks:
                return

        except Exception as e:
            err_msg = str(e).lower()
            is_temporary_error = any(k in err_msg for k in ["503", "429", "404", "unavailable", "high demand", "resource_exhausted", "quota", "overloaded"])
            
            if not is_temporary_error:
                raise e
            
            # Padayon sa sunod nga fallback model
            if idx == len(models_to_try) - 1:
                raise Exception(f"Tanang models busy karon sa Google servers. Last error: {str(e)}")