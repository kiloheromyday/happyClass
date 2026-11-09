"""Local stdio MCP adapter. No camera access, file paths, URLs, or database tools."""
import base64
import binascii
import json
import os
from typing import Annotated

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ai_service.config import MAX_FRAME_BYTES, confidence_threshold, service_token
from ai_service.contracts import InferenceResult

mcp = FastMCP('HappyClass Emotion Tools', instructions='Analyze only an image explicitly supplied by the user. Facial expressions are not psychological diagnoses. No camera, identity matching, or database writes are performed.')


def service_url():
    return os.getenv('EMOJI_AI_URL', 'http://127.0.0.1:18081').rstrip('/')


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
async def model_status() -> dict:
    """Check the configured local inference service without exposing its credential."""
    ready = False
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False, follow_redirects=False) as client:
            response = await client.get(service_url() + '/health')
        ready = response.status_code == 200 and response.json().get('data', {}).get('ready') is True
    except (httpx.HTTPError, ValueError):
        pass
    configured = service_token() is not None
    return {'ready': ready and configured, 'authentication_configured': configured, 'stores_raw_media': False}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False))
async def analyze_emotion(jpeg_base64: Annotated[str, Field(max_length=1_333_340)]) -> dict:
    """Classify an explicitly provided base64 JPEG (at most 1 MB). No image is saved or added to a classroom."""
    try:
        data = base64.b64decode(jpeg_base64, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError('Please supply standard base64 JPEG data without a data-URL prefix') from error
    if not data.startswith(b'\xff\xd8') or not 1 <= len(data) <= MAX_FRAME_BYTES:
        raise ValueError('A JPEG no larger than 1 MB is required')
    token = service_token()
    if not token:
        raise ValueError('The inference service has not been configured')
    try:
        async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as client:
            response = await client.post(service_url() + '/infer', content=data,
                                         headers={'Authorization': f'Bearer {token}', 'Content-Type': 'image/jpeg'})
        response.raise_for_status()
        result = InferenceResult.model_validate(response.json())
    except (httpx.HTTPError, ValueError) as error:
        raise ValueError('Inference failed; check the local model service and JPEG dimensions') from error
    threshold = confidence_threshold()
    faces = [item.model_dump() for item in result.faces if item.confidence >= threshold and item.emotion != 'CONTEMPT']
    return {'detected': result.detected, 'processed': result.processed, 'faces': faces,
            'filtered': result.processed - len(faces), 'min_confidence': threshold, 'stores_raw_media': False}


@mcp.resource('happyclass://ai/capabilities')
def capabilities() -> str:
    return json.dumps({'input': 'base64 JPEG', 'max_bytes': MAX_FRAME_BYTES,
                       'emotions': ['NEUTRAL', 'HAPPY', 'SURPRISED', 'SAD', 'ANGRY', 'DISGUST', 'FEAR'],
                       'camera_access': False, 'database_writes': False, 'stores_raw_media': False,
                       'warning': 'Expression classification does not measure psychological state or teaching quality.'})


if __name__ == '__main__':
    mcp.run(transport='stdio')
