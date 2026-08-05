/**
 * Text-to-speech endpoint using Azure AI Speech neural voices.
 *
 * Accepts text and returns synthesized audio using Azure's neural TTS,
 * falling back gracefully when Azure Speech is not configured (the client
 * will use browser speechSynthesis instead).
 */

import { NextRequest, NextResponse } from "next/server";

const AZURE_SPEECH_KEY = process.env.AZURE_SPEECH_API_KEY || "";
const AZURE_SPEECH_REGION = process.env.AZURE_SPEECH_REGION || "eastus2";

// Neural voice to use (Azure AI Speech neural voices are high-quality)
// en-US-AvaMultilingualNeural is a natural-sounding multilingual voice
const VOICE_NAME = "en-US-AvaMultilingualNeural";

export async function POST(request: NextRequest) {
  // If Azure Speech is not configured, return 501 (Not Implemented) so the client
  // knows to fall back to browser speechSynthesis
  if (!AZURE_SPEECH_KEY) {
    return NextResponse.json(
      { error: "Azure Speech not configured - use browser fallback" },
      { status: 501 }
    );
  }

  try {
    const { text } = await request.json();

    if (!text || typeof text !== "string") {
      return NextResponse.json({ error: "Text is required" }, { status: 400 });
    }

    // Azure Speech REST API endpoint for text-to-speech
    const speechUrl = `https://${AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1`;

    // SSML for neural voice with natural prosody
    const ssml = `
      <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">
        <voice name="${VOICE_NAME}">
          <prosody rate="1.04">
            ${escapeXml(text)}
          </prosody>
        </voice>
      </speak>
    `.trim();

    const response = await fetch(speechUrl, {
      method: "POST",
      headers: {
        "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-16khz-32kbitrate-mono-mp3",
      },
      body: ssml,
    });

    if (!response.ok) {
      console.error("Azure Speech API error:", response.status, response.statusText);
      return NextResponse.json(
        { error: `Speech synthesis failed: ${response.statusText}` },
        { status: response.status }
      );
    }

    // Return the audio data with appropriate headers
    const audioBuffer = await response.arrayBuffer();

    return new NextResponse(audioBuffer, {
      headers: {
        "Content-Type": "audio/mpeg",
        "Content-Length": audioBuffer.byteLength.toString(),
        // Cache audio for 1 hour (same text = same audio)
        "Cache-Control": "public, max-age=3600",
      },
    });
  } catch (error) {
    console.error("TTS error:", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}

function escapeXml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}
