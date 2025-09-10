#!/usr/bin/env python3
"""
Brightside Health AI Studio - Setup Configuration
"""

from setuptools import setup, find_packages

def read_requirements():
    with open('requirements.txt', 'r') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name="brightside-health-ai",
    version="1.0.0",
    description="AI-powered clinical decision support for depression and anxiety",
    
    # Package configuration
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    
    # Dependencies
    install_requires=read_requirements(),
    python_requires=">=3.9",
    
    # CLI commands
    entry_points={
        "console_scripts": [
            "brightside-run=scripts.run_pipeline:main",
        ],
    },
    
    # Classification
    classifiers=[
        "Development Status :: 4 - Beta",
        "Programming Language :: Python :: 3.9",
    ],
)