/**
 * Text-to-speech endpoint using Azure AI Speech neural voices.
 *
 * Accepts text and returns synthesized audio using Azure's neural TTS,
 * falling back gracefully when Azure Speech is not configured (the client
 * will use browser speechSynthesis instead).
 *
 * Returns raw MP3 bytes for the browser's Web Audio playback path.
 */

import { NextResponse } from "next/server";
import { BackendError, mintAccessToken } from "@/lib/backendAuth";

const AZURE_SPEECH_KEY = process.env.AZURE_SPEECH_API_KEY || "";
const AZURE_SPEECH_REGION = process.env.AZURE_SPEECH_REGION || "eastus2";

// Neural voice to use (Azure AI Speech neural voices are high-quality)
// en-US-JennyNeural is a professional, warm, and natural voice
const VOICE_NAME = "en-US-JennyNeural";
const MAX_SPEECH_TEXT_LENGTH = 2_000;

export async function POST(request: Request) {
  // Speech is a billable Azure service. Require the same signed-in session used by
  // the other server-side API routes before accepting work from the browser.
  try {
    await mintAccessToken(request.headers.get("cookie") ?? "");
  } catch (error) {
    if (error instanceof BackendError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    return NextResponse.json({ error: "Could not verify your session." }, { status: 503 });
  }

  // If Azure Speech is not configured, return 501 (Not Implemented) so the client
  // knows to fall back to browser speechSynthesis
  if (!AZURE_SPEECH_KEY) {
    console.log("[speech] Azure Speech not configured - KEY missing");
    return NextResponse.json(
      { error: "Azure Speech not configured - use browser fallback" },
      { status: 501 }
    );
  }

  try {
    const { text } = await request.json();

    if (!text || typeof text !== "string" || !text.trim()) {
      return NextResponse.json({ error: "Text is required" }, { status: 400 });
    }
    if (text.length > MAX_SPEECH_TEXT_LENGTH) {
      return NextResponse.json(
        { error: `Text must be at most ${MAX_SPEECH_TEXT_LENGTH} characters.` },
        { status: 413 },
      );
    }

    // Azure Speech REST API endpoint for text-to-speech
    const speechUrl = `https://${AZURE_SPEECH_REGION}.tts.speech.microsoft.com/cognitiveservices/v1`;

    // SSML for neural voice with natural prosody
    const ssml = `
      <speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">
        <voice name="${VOICE_NAME}">
          <prosody rate="0.85">
            ${escapeXml(text)}
          </prosody>
        </voice>
      </speak>
    `.trim();

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000); // 5 second timeout

    try {
      const response = await fetch(speechUrl, {
        method: "POST",
        headers: {
          "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
          "Content-Type": "application/ssml+xml",
          "X-Microsoft-OutputFormat": "audio-16khz-32kbitrate-mono-mp3",
        },
        body: ssml,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      console.log("[speech] Azure Speech API response:", response.status, response.statusText);

      if (!response.ok) {
        // Do not log the response body: an upstream error can echo submitted text.
        console.error("Azure Speech API error:", response.status, response.statusText);
        return NextResponse.json(
          { error: `Speech synthesis failed: ${response.statusText}` },
          { status: response.status }
        );
      }

      // Return the audio data with appropriate headers
      const audioBuffer = await response.arrayBuffer();

      console.log("[speech] Successfully synthesized audio, size:", audioBuffer.byteLength);

      return new NextResponse(audioBuffer, {
        headers: {
          "Content-Type": "audio/mpeg",
          "Content-Length": audioBuffer.byteLength.toString(),
          // Speech can contain user content; do not allow a shared cache to retain it.
          "Cache-Control": "private, no-store",
        },
      });
    } catch (fetchError: any) {
      clearTimeout(timeoutId);
      if (fetchError.name === 'AbortError') {
        console.error("[speech] Request timeout after 5 seconds");
        return NextResponse.json(
          { error: "Speech synthesis timeout - use browser fallback" },
          { status: 504 }
        );
      }
      throw fetchError;
    }
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
