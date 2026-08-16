/**
 * Text-to-speech endpoint using Azure AI Speech neural voices.
 *
 * Accepts text and returns synthesized audio using Azure's neural TTS,
 * falling back gracefully when Azure Speech is not configured (the client
 * will use browser speechSynthesis instead).
 *
 * Two output shapes, selected by the optional `format` field in the request body:
 * - default/"mp3": raw MP3 bytes (existing behavior), consumed by useVoiceConversation.ts's
 *   Web Audio API playback path when the avatar isn't in use.
 * - "pcm24k": JSON `{ audio: "<base64>" }` of raw 16-bit signed PCM at 24kHz mono — the
 *   exact format LiveAvatar's repeatAudio() requires. Its own SDK's repeat()/message()
 *   (text-based, server-side TTS) only work in FULL-mode sessions; docs-api always mints
 *   LITE-mode tokens (liveavatar.py), so useLiveAvatar.ts's speak() must bring its own
 *   already-synthesized audio rather than ask LiveAvatar to speak text — confirmed via
 *   HeyGen's own demo app (heygen-com/live-avatar-js-sdk, useAvatarActions.ts) and the
 *   SDK's bundled audio_utils.ts chunking helper, which documents the 24kHz/16-bit/mono
 *   contract. JSON (not raw bytes) because the caller needs a base64 string to hand
 *   straight to repeatAudio(), not an ArrayBuffer to decode/play locally.
 */

import { NextRequest, NextResponse } from "next/server";

const AZURE_SPEECH_KEY = process.env.AZURE_SPEECH_API_KEY || "";
const AZURE_SPEECH_REGION = process.env.AZURE_SPEECH_REGION || "eastus2";

// Neural voice to use (Azure AI Speech neural voices are high-quality)
// en-US-JennyNeural is a professional, warm, and natural voice
const VOICE_NAME = "en-US-JennyNeural";

export async function POST(request: NextRequest) {
  // If Azure Speech is not configured, return 501 (Not Implemented) so the client
  // knows to fall back to browser speechSynthesis
  if (!AZURE_SPEECH_KEY) {
    console.log("[speech] Azure Speech not configured - KEY missing");
    return NextResponse.json(
      { error: "Azure Speech not configured - use browser fallback" },
      { status: 501 }
    );
  }

  console.log("[speech] Azure Speech configured, region:", AZURE_SPEECH_REGION, "key length:", AZURE_SPEECH_KEY.length);

  try {
    const { text, format } = await request.json();
    const wantsPcm24k = format === "pcm24k";

    if (!text || typeof text !== "string") {
      return NextResponse.json({ error: "Text is required" }, { status: 400 });
    }

    console.log("[speech] Synthesizing text:", text.substring(0, 50), "format:", format ?? "mp3");

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

    console.log("[speech] Calling Azure Speech API at:", speechUrl);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000); // 5 second timeout

    try {
      const response = await fetch(speechUrl, {
        method: "POST",
        headers: {
          "Ocp-Apim-Subscription-Key": AZURE_SPEECH_KEY,
          "Content-Type": "application/ssml+xml",
          "X-Microsoft-OutputFormat": wantsPcm24k
            ? "raw-24khz-16bit-mono-pcm"
            : "audio-16khz-32kbitrate-mono-mp3",
        },
        body: ssml,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      console.log("[speech] Azure Speech API response:", response.status, response.statusText);

      if (!response.ok) {
        const errorText = await response.text();
        console.error("Azure Speech API error:", response.status, response.statusText, errorText);
        return NextResponse.json(
          { error: `Speech synthesis failed: ${response.statusText}` },
          { status: response.status }
        );
      }

      // Return the audio data with appropriate headers
      const audioBuffer = await response.arrayBuffer();

      console.log("[speech] Successfully synthesized audio, size:", audioBuffer.byteLength);

      if (wantsPcm24k) {
        return NextResponse.json({ audio: Buffer.from(audioBuffer).toString("base64") });
      }

      return new NextResponse(audioBuffer, {
        headers: {
          "Content-Type": "audio/mpeg",
          "Content-Length": audioBuffer.byteLength.toString(),
          // Cache audio for 1 hour (same text = same audio)
          "Cache-Control": "public, max-age=3600",
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
