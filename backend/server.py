import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from livekit import api

# Hardcoded Credentials as requested for debugging
LIVEKIT_API_KEY = "APIB2vg7QvPMNUA"
LIVEKIT_API_SECRET = "avWelhyxeUhbBHWYePf44XcV5uwejXBm6CNG06kNKj4B"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/get-token")
async def get_token(room: str, identity: str):
    if not room or not identity:
        raise HTTPException(status_code=400, detail="Room and identity are required")

    try:
        # Create a token for the room
        token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET) \
            .with_identity(identity) \
            .with_grants(api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True
            ))
        
        return {"token": token.to_jwt()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
