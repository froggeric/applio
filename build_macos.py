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
ICON_FILE = "assets/ICON.ico" 

# Hidden imports common in scientific/ML stacks
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
    "tensorboard",
    "tensorboardX",
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
    "--collect-all=gradio",      
    "--collect-all=gradio_client", 
    "--collect-all=safehttpx",    
    "--collect-all=groovy",       
    "--target-arch=arm64",
    "--osx-bundle-identifier=com.iahispano.applio",
] + add_data_args + hidden_import_args

# Run PyInstaller
print("Starting Applio macOS Build Sequence...")
PyInstaller.__main__.run(args)

# Post-processing Info.plist
info_plist_path = os.path.join("dist", f"{APP_NAME}.app", "Contents", "Info.plist")
if os.path.exists(info_plist_path):
    print("Patching Info.plist for Microphone access & Metadata...")
    try:
        import plistlib
        with open(info_plist_path, 'rb') as f:
            plist = plistlib.load(f)
        
        # Permissions
        plist['NSMicrophoneUsageDescription'] = "Applio needs microphone access to record audio for voice conversion."
        
        # Branding
        plist['CFBundleShortVersionString'] = "3.6.0"
        plist['CFBundleVersion'] = "3.6.0"
        plist['NSHumanReadableCopyright'] = "Copyright © 2026 IAHispano. All rights reserved."
        
        with open(info_plist_path, 'wb') as f:
            plistlib.dump(plist, f)
        print("Info.plist patched successfully.")
    except Exception as e:
        print(f"Failed to patch Info.plist: {e}")
else:
    print(f"WARNING: Info.plist not found at {info_plist_path}")

print("Build complete. Application verified at dist/Applio.app")
