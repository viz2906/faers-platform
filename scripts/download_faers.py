import os
import sys
import zipfile
import requests
import time

def download_file(url, dest_path):
    print(f"[DOWNLOAD] Starting download from {url} to {dest_path}...")
    temp_dest = dest_path + ".tmp"
    
    # Try downloading with a stream
    try:
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(temp_dest, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        sys.stdout.write(f"\r[PROGRESS] {downloaded // (1024*1024)}MB / {total_size // (1024*1024)}MB ({percent:.1f}%)")
                    else:
                        sys.stdout.write(f"\r[PROGRESS] {downloaded // (1024*1024)}MB downloaded")
                    sys.stdout.flush()
        
        sys.stdout.write("\n")
        # Swap temp file to actual file
        if os.path.exists(dest_path):
            os.remove(dest_path)
        os.rename(temp_dest, dest_path)
        print("[OK] Download finished.")
        return True
    except Exception as e:
        print(f"\n[ERROR] Download interrupted: {e}")
        if os.path.exists(temp_dest):
            try:
                os.remove(temp_dest)
            except:
                pass
        return False

def verify_zip(zip_path):
    print(f"[VERIFY] Checking integrity of {zip_path}...")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad_file = zf.testzip()
            if bad_file:
                print(f"[ERROR] Corrupted file in zip: {bad_file}")
                return False
            print("[OK] Zip file integrity verified successfully.")
            return True
    except Exception as e:
        print(f"[ERROR] Zip file is invalid: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        quarter = "2026q1"
    else:
        quarter = sys.argv[1].lower()
        
    dest_dir = f"./data/raw/{quarter}"
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = f"{dest_dir}/faers_ascii_{quarter}.zip"
    
    # Try lowercase first, then uppercase Q
    urls = [
        f"https://fis.fda.gov/content/Exports/faers_ascii_{quarter}.zip",
        f"https://fis.fda.gov/content/Exports/faers_ascii_{quarter.replace('q', 'Q')}.zip"
    ]
    
    # If the file already exists and is valid, skip
    if os.path.exists(dest_path) and verify_zip(dest_path):
        print(f"[SKIP] Valid zip already exists: {dest_path}")
        return 0
        
    for attempt in range(1, 6):
        print(f"\n=== Attempt {attempt} of 5 ===")
        for url in urls:
            success = download_file(url, dest_path)
            if success:
                if verify_zip(dest_path):
                    print(f"[SUCCESS] Downloaded and verified: {dest_path}")
                    return 0
                else:
                    print("[WARNING] Verification failed. Deleting corrupted file.")
                    try:
                        os.remove(dest_path)
                    except:
                        pass
            print("[RETRY] Waiting 5 seconds before retrying...")
            time.sleep(5)
            
    print("[FATAL] All attempts to download and verify the zip file failed.")
    return 1

if __name__ == "__main__":
    sys.exit(main())
