import asyncio
import base64
import json
import os
import sys

import httpx
import pytest

pytest.importorskip('mcp')
from ai_service import mcp_server


def test_mcp_inference_filters_results_and_does_not_accept_files_or_urls(monkeypatch):
    monkeypatch.setenv('EMOJI_AI_TOKEN', 'mcp-test-' + 'x' * 48)
    monkeypatch.setenv('EMOJI_AI_MIN_CONFIDENCE', '.7')
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={'detected': 3, 'processed': 3, 'faces': [
            {'emotion': 'HAPPY', 'confidence': .9}, {'emotion': 'SAD', 'confidence': .3}, {'emotion': 'CONTEMPT', 'confidence': .99}]})

    original = httpx.AsyncClient
    monkeypatch.setattr(mcp_server.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    result = asyncio.run(mcp_server.analyze_emotion(base64.b64encode(b'\xff\xd8test-jpeg').decode()))
    assert result['faces'] == [{'emotion': 'HAPPY', 'confidence': .9}]
    assert result['filtered'] == 2 and result['stores_raw_media'] is False
    assert requests[0].headers['Content-Type'] == 'image/jpeg'
    for invalid in ('https://example.com/photo.jpg', 'C:/private.jpg', 'data:image/jpeg;base64,aGVsbG8=', 'aGVsbG8='):
        with pytest.raises(ValueError):
            asyncio.run(mcp_server.analyze_emotion(invalid))
    assert len(requests) == 1


def test_mcp_stdio_protocol_handshake_tools_resource_and_error():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def check():
        params = StdioServerParameters(command=sys.executable, args=['-m', 'ai_service.mcp_server'], env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {item.name for item in tools.tools} == {'analyze_emotion', 'model_status'}
                resource = await session.read_resource('happyclass://ai/capabilities')
                capability = json.loads(resource.contents[0].text)
                assert capability['database_writes'] is False and capability['camera_access'] is False
                result = await session.call_tool('analyze_emotion', {'jpeg_base64': 'not a JPEG'})
                assert result.isError

    asyncio.run(check())
