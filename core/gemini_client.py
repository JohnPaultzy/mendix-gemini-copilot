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
    Mo-stream og tubag gikan sa Gemini nga adunay 4-Tier Automatic Fallback:
    1. Selected Model (e.g. gemini-3.7-flash)
    2. gemini-2.5-flash (1st backup)
    3. gemini-2.5-pro (2nd backup)
    4. gemini-1.5-flash (final fallback)
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
    
    # 1. Attachments handling
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

    # 2. Multi-Tier Fallback Chain
    fallback_priority = [
        "gemini-3.7-flash",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-flash"
    ]
    
    # I-una ang napili nga model, unya isunod ang nahibiling backup models
    models_to_try = [model_name] + [m for m in fallback_priority if m != model_name]

    for idx, current_model in enumerate(models_to_try):
        try:
            # Kung dili kini ang unang model, pahibaloon ang user nga gibalhin ang model
            if idx > 0:
                yield f"> ⚠️ *Pahibalo: Ang `{models_to_try[idx-1]}` nakasinati og traffic spike/503. Awtomatikong mibalhin sa fallback: `{current_model}`...*\n\n"

            response_stream = client.models.generate_content_stream(
                model=current_model,
                contents=formatted_contents,
                config=config_params
            )
            
            has_emitted = False
            for chunk in response_stream:
                if chunk.text:
                    has_emitted = True
                    yield chunk.text
            
            # Kung nakatubag og tarong, undangon na ang pag-try sa ubang backup models
            if has_emitted:
                return

        except Exception as e:
            err_msg = str(e).lower()
            # Susiha kung temporary network/server/quota error (503, 429, unavailable, high demand)
            is_temporary_error = any(k in err_msg for k in ["503", "429", "unavailable", "high demand", "resource_exhausted", "quota", "overloaded"])
            
            if not is_temporary_error:
                # Kung dili server error (e.g. invalid API key o bad prompt), i-raise dayon
                raise e
            
            # Kung naabot na sa pinaka-katapusang backup model ug nag-fail gihapon tanan
            if idx == len(models_to_try) - 1:
                raise Exception(f"Tanang 4 ka models ({', '.join(models_to_try)}) busy karon sa Google servers. Palihug sulayi pag-usab human sa pipila ka segundos. Last error: {str(e)}")