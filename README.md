# 3DS Banner Sound Extractor

A small cross-platform Python tool that extracts Nintendo 3DS banner audio from supported ROM/container files and converts it to MP3.

It works on:

- Windows
- macOS, including Apple Silicon and Intel Macs
- Linux

The script downloads/prepares its helper tools automatically into a local `_3ds_banner_tools` folder beside your ROMs.

## What it outputs

For a ROM named:

```text
Game Name.3ds
```

The output will be:

```text
Extracted Banner Sounds/Game Name_banner_sound.mp3
```

Supported input extensions:

```text
.3ds, .cci, .cia, .cxi, .app
```

## Where to put the script

Copy the Python script into the same folder as your ROMs.

Example:

```text
Nintendo - Nintendo 3DS/
├── extract_3ds_banner_sound.py
├── Game 1.3ds
├── Game 2.3ds
└── Some Subfolder/
    └── Game 3.3ds
```

The tool will create these folders automatically:

```text
_3ds_banner_tools/
_3ds_banner_work/
Extracted Banner Sounds/
```

## Windows

Open PowerShell in the ROM folder.

Check the script:

```powershell
python .\extract_3ds_banner_sound.py --version
python .\extract_3ds_banner_sound.py --platform-info
```

Install/download dependencies:

```powershell
python .\extract_3ds_banner_sound.py --install-tools-only .
```

Batch process ROMs in the current folder only:

```powershell
python .\extract_3ds_banner_sound.py .
```

Batch process ROMs in the current folder and all subfolders:

```powershell
python .\extract_3ds_banner_sound.py . --recursive
```

Overwrite existing MP3 files:

```powershell
python .\extract_3ds_banner_sound.py . --recursive --force
```

If `python` does not work, try `py` instead:

```powershell
py .\extract_3ds_banner_sound.py . --recursive
```

## macOS

Open Terminal in the ROM folder.

Check the script:

```bash
python3 extract_3ds_banner_sound.py --version
python3 extract_3ds_banner_sound.py --platform-info
```

Install/download dependencies:

```bash
python3 extract_3ds_banner_sound.py --install-tools-only .
```

Batch process ROMs in the current folder only:

```bash
python3 extract_3ds_banner_sound.py .
```

Batch process ROMs in the current folder and all subfolders:

```bash
python3 extract_3ds_banner_sound.py . --recursive
```

Overwrite existing MP3 files:

```bash
python3 extract_3ds_banner_sound.py . --recursive --force
```

On Apple Silicon Macs, if you want to force native Homebrew Python instead of an older Intel/Rosetta Python, use:

```bash
/opt/homebrew/bin/python3 extract_3ds_banner_sound.py --platform-info
/opt/homebrew/bin/python3 extract_3ds_banner_sound.py . --recursive
```

## Linux

Open a terminal in the ROM folder.

Check the script:

```bash
python3 extract_3ds_banner_sound.py --version
python3 extract_3ds_banner_sound.py --platform-info
```

Install/download dependencies:

```bash
python3 extract_3ds_banner_sound.py --install-tools-only .
```

Batch process ROMs in the current folder only:

```bash
python3 extract_3ds_banner_sound.py .
```

Batch process ROMs in the current folder and all subfolders:

```bash
python3 extract_3ds_banner_sound.py . --recursive
```

Overwrite existing MP3 files:

```bash
python3 extract_3ds_banner_sound.py . --recursive --force
```

## Single ROM command

You can also process one ROM directly:

Windows:

```powershell
python .\extract_3ds_banner_sound.py "Game Name.3ds"
```

macOS/Linux:

```bash
python3 extract_3ds_banner_sound.py "Game Name.3ds"
```

## Dependency and licensing notes

This repository does not include the third-party helper tools. The script downloads or uses them at runtime.

Third-party tools used:

- `ctrtool` from Project_CTR: used to extract Nintendo 3DS containers/ExeFS.
- `vgmstream-cli`: used to decode BCWAV/CWAV banner audio to WAV.
- `ffmpeg`: used to convert WAV to MP3.
- `imageio-ffmpeg`: Python package used as a fallback way to obtain an FFmpeg binary.

Relevant upstream pages:

- Project_CTR / ctrtool: https://github.com/3DSGuy/Project_CTR
- vgmstream: https://github.com/vgmstream/vgmstream and https://vgmstream.org/
- FFmpeg legal/licensing information: https://ffmpeg.org/legal.html
- imageio-ffmpeg: https://pypi.org/project/imageio-ffmpeg/

FFmpeg is licensed mainly under LGPL 2.1 or later, but some builds/options may be GPL depending on enabled components. If you redistribute FFmpeg binaries yourself, check the FFmpeg licensing requirements carefully.

`imageio-ffmpeg` is listed on PyPI as BSD-2-Clause licensed.

If you redistribute this script only, without bundling the downloaded helper tools, you should still mention that the script downloads and uses those third-party tools and that users should comply with their licenses.

## Legal note

Use this only with games/files you are legally entitled to process. The tool does not provide game files, keys, BIOS files, copyrighted Nintendo content, or decryption keys.
