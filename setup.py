"""
setup.py — GramWrite package setup
"""

from pathlib import Path
from setuptools import setup, find_packages

readme = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")

setup(
    name="gramwrite",
    version="1.0.0",
    description="The Invisible Editor for Screenwriters",
    long_description=readme,
    long_description_content_type="text/markdown",
    author="GramWrite Contributors",
    license="MIT",
    python_requires=">=3.10",
    packages=find_packages(),
    install_requires=[
        "aiohttp>=3.9.0",
        "PyQt6>=6.6.0",
        "PyYAML>=6.0",
    ],
    extras_require={
        "macos": [
            "pyobjc-framework-Cocoa>=10.0",
            "pyobjc-framework-ApplicationServices>=10.0",
        ],
        "windows": [
            "uiautomation>=2.0.18",
            "psutil>=5.9.0",
        ],
        "linux": [
            "pyatspi>=2.46.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "gramwrite=gramwrite.__main__:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: X11 Applications :: Qt",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Text Editors",
        "Topic :: Multimedia :: Sound/Audio",
    ],
)
