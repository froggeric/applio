import PyInstaller.__main__
import os
import shutil

# Clean up previous builds
if os.path.exists("dist"):
    shutil.rmtree("dist")
if os.path.exists("build"):
    shutil.rmtree("build")

# Define build parameters
APP_NAME = "Applio"
ENTRY_POINT = "macos_wrapper.py"
ICON_FILE = "assets/ICON.ico" # PyInstaller handles conversion

# Hidden imports common in scientific/ML stacks (Subagent Nova's Review)
HIDDEN_IMPORTS = [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "gradio.networking",
    "gradio.themes",
    "torch",
    "numpy",
    "passlib.handlers.bcrypt",
    "scipy.signal",
    "scipy.special.cython_special",
    "scipy.linalg.cy_linalg",
    "sklearn.utils._typedefs",
    "fairseq.models.wav2vec.wav2vec2",
    "fairseq.tasks.audio_pretraining",
    "fairseq.modules.checkpoint_activations",
    "fairseq.dataclass.configs",
    "soundfile",
    "_soundfile",
    "webview.platforms.cocoa",
]

# Collect data files
# Format: "source:dest"
datas = [
    ("assets", "assets"),
    ("logs", "logs"),
    ("rvc", "rvc"),
    ("tabs", "tabs"),
    ("core.py", "."),
    ("app.py", "."),
]

# Construct --add-data arguments
add_data_args = []
for source, dest in datas:
    if os.path.exists(source):
        add_data_args.append(f"--add-data={source}:{dest}")
    else:
        print(f"WARNING: Source {source} not found, skipping.")

# Construct --hidden-import arguments
hidden_import_args = []
for lib in HIDDEN_IMPORTS:
    hidden_import_args.append(f"--hidden-import={lib}")

# PyInstaller arguments
args = [
    ENTRY_POINT,
    "--name=Applio",
    "--windowed", # No console
    "--noconfirm",
    "--clean",
    f"--icon={ICON_FILE}",
    "--collect-all=torch",
    "--collect-all=torchaudio",
    "--target-arch=arm64", # Pin to Apple Silicon
] + add_data_args + hidden_import_args

# Run PyInstaller
print("Starting PyInstaller build...")
PyInstaller.__main__.run(args)

# Post-processing Info.plist
info_plist_path = os.path.join("dist", f"{APP_NAME}.app", "Contents", "Info.plist")
if os.path.exists(info_plist_path):
    print("Patching Info.plist for Microphone access...")
    try:
        import plistlib
        with open(info_plist_path, 'rb') as f:
            plist = plistlib.load(f)
        
        # Add Microphone Usage Description
        plist['NSMicrophoneUsageDescription'] = "Applio needs microphone access to record audio for voice conversion."
        
        with open(info_plist_path, 'wb') as f:
            plistlib.dump(plist, f)
        print("Info.plist patched successfully.")
    except Exception as e:
        print(f"Failed to patch Info.plist: {e}")
else:
    print(f"WARNING: Info.plist not found at {info_plist_path}")

print("Build complete. Application is in dist/")
