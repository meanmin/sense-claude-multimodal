"""
sense-claude-multimodal: Give Claude Ears
Step 1: Extract audio/frames from video + Analyze sound with Cochl.Sense
Step 2: Feed results into Claude Code for Vision analysis + combined judgment
"""

import os
import sys
import json
import subprocess
import base64
import glob
import time
from pathlib import Path
from dotenv import load_dotenv
import requests

load_dotenv()

# --- Config ---
COCHL_API_KEY = os.getenv("COCHL_API_KEY")
COCHL_BASE_URL = "https://api.cochl.ai/sense/api/v1"
OUTPUT_DIR = Path(__file__).parent.parent / "output"
FRAME_INTERVAL = 3  # Extract 1 frame every N seconds
CHUNK_SIZE = 1_000_000  # 1MB chunks for upload


def extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio from video using ffmpeg."""
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vn", "-acodec", "pcm_s16le", "-ar", "22050", "-ac", "1",
        output_path, "-y"
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"[+] Audio extracted: {output_path}")
    return output_path


def extract_frames(video_path: str, output_dir: str, interval: int = FRAME_INTERVAL) -> list[str]:
    """Extract frames from video at regular intervals using ffmpeg."""
    os.makedirs(output_dir, exist_ok=True)
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"fps=1/{interval}",
        os.path.join(output_dir, "frame_%04d.jpg"), "-y"
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    frames = sorted(glob.glob(os.path.join(output_dir, "frame_*.jpg")))
    print(f"[+] Frames extracted: {len(frames)} frames")
    return frames


def analyze_sound(audio_path: str) -> dict:
    """Analyze audio using Cochl.Sense REST API."""
    headers = {"x-api-key": COCHL_API_KEY, "Content-Type": "application/json"}

    # Read file info
    file_size = os.path.getsize(audio_path)
    file_name = os.path.basename(audio_path)

    # Step 1: Create session
    create_body = {
        "type": "file",
        "content_type": "audio/wav",
        "total_size": file_size,
        "file_name": file_name,
    }
    resp = requests.post(f"{COCHL_BASE_URL}/audio_sessions/", headers=headers, json=create_body)
    resp.raise_for_status()
    session = resp.json()
    session_id = session["session_id"]
    print(f"    Session created: {session_id}")

    # Step 2: Upload chunks
    with open(audio_path, "rb") as f:
        chunk_seq = 0
        while True:
            chunk_data = f.read(CHUNK_SIZE)
            if not chunk_data:
                break
            encoded = base64.standard_b64encode(chunk_data).decode("utf-8")
            upload_body = {"data": encoded}
            resp = requests.put(
                f"{COCHL_BASE_URL}/audio_sessions/{session_id}/chunks/{chunk_seq}",
                headers=headers, json=upload_body
            )
            resp.raise_for_status()
            chunk_seq += 1
    print(f"    Uploaded {chunk_seq} chunk(s)")

    # Step 3: Poll for results
    print("    Waiting for analysis...", end="", flush=True)
    while True:
        resp = requests.get(
            f"{COCHL_BASE_URL}/audio_sessions/{session_id}/results",
            headers=headers
        )
        resp.raise_for_status()
        result = resp.json()
        if result["state"] == "done":
            break
        if result["state"] == "error":
            raise Exception(f"Cochl.Sense error: {result.get('error', 'unknown')}")
        print(".", end="", flush=True)
        time.sleep(2)
    print(" done!")

    # Parse events
    sound_events = []
    for event in result.get("data", []):
        for tag in event.get("tags", []):
            sound_events.append({
                "tag": tag["name"],
                "probability": round(tag["probability"], 3),
                "start_time": event["start_time"],
                "end_time": event["end_time"],
            })

    print(f"[+] Sound analysis complete: {len(sound_events)} events detected")
    return {"events": sound_events}


def main():
    if len(sys.argv) < 3:
        print("Usage: python analyze_video.py <video_path> <scenario>")
        print("  scenario: 'parking_accident' or 'home_intrusion'")
        sys.exit(1)

    video_path = sys.argv[1]
    scenario = sys.argv[2]

    if not os.path.exists(video_path):
        print(f"Error: Video file not found: {video_path}")
        sys.exit(1)

    if not COCHL_API_KEY:
        print("Error: COCHL_API_KEY not set. Copy .env.example to .env and add your key.")
        sys.exit(1)

    # Setup output directory
    run_dir = OUTPUT_DIR / scenario
    os.makedirs(run_dir, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  sense-claude-multimodal: Give Claude Ears")
    print(f"  Scenario: {scenario}")
    print(f"{'='*60}\n")

    # Step 1: Extract audio and frames
    print("[Step 1] Extracting audio and frames...")
    audio_path = str(run_dir / "audio.wav")
    frames_dir = str(run_dir / "frames")
    extract_audio(video_path, audio_path)
    frames = extract_frames(video_path, frames_dir)

    # Step 2: Analyze sound with Cochl.Sense
    print("\n[Step 2] Analyzing sound with Cochl.Sense...")
    sound_result = analyze_sound(audio_path)

    # Save results
    result_path = run_dir / "sound_analysis.json"
    with open(result_path, "w") as f:
        json.dump(sound_result, f, indent=2, ensure_ascii=False)

    # Summary
    print(f"\n{'='*60}")
    print(f"  PREPARATION COMPLETE")
    print(f"{'='*60}")
    print(f"\n  Sound analysis : {result_path}")
    print(f"  Frames         : {frames_dir}/ ({len(frames)} frames)")
    print(f"\n  Next step: Open Claude Code and ask it to analyze the frames")
    print(f"  and combine with sound results for a final judgment.")
    print(f"\n  Example prompt for Claude Code:")
    print(f"  ───────────────────────────────")
    print(f'  "Look at the frames in {frames_dir}/')
    print(f'   and read the sound analysis in {result_path}.')
    print(f'   Combine both to assess what happened in this {scenario} scenario."')
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
