import sys
from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse

app = FastAPI(title="ACCCE Mock Licensing Server")

COURSERA_LAYOUT_MAP = {
    "video_player": "video",
    "mark_completed": "button:has-text('Mark as completed'), button:has-text('Mark as Completed')",
    "quiz_container": "div[data-testid^='part-Submission_'], .rc-Option, .rc-FormQuestion, .question-container, .rc-Form",
    "start_quiz_button": "button:has-text('Start'), button:has-text('Resume')",
    "submit_quiz_button": "button:has-text('Submit')",
    "text_inputs": "textarea, input[type='text']",
    "choice_inputs": "input[type='checkbox'], input[type='radio']",
    "agreement_checkbox": "input[type='checkbox']",
    "modal_dialog": ".rc-Modal, .cds-dialog",
    "modal_close_button": "button:has-text('Continue'), button:has-text('OK')",
    "enroll_button": "button:text-is('Enroll')",
    "enroll_modal_button": "button:has-text('Go to course')"
}

@app.get("/")
def read_root():
    return {"status": "mock_online"}

@app.get("/api/v1/layout-map")
def get_layout_map(x_api_key: str = Header(None)):
    if x_api_key == "test-success-key":
        return {
            "status": "authorized",
            "credits": 4,
            "layout_map": COURSERA_LAYOUT_MAP
        }
    elif x_api_key == "test-paywall-key":
        return JSONResponse(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            content={
                "status": "payment_required",
                "payment_details": {
                    "destination_address": "0xMockMasterWalletAddress123456789",
                    "amount": 20.0003,
                    "suggested_chain": "polygon",
                    "token": "USDT"
                }
            }
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Mock Error: Invalid API Key."
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
