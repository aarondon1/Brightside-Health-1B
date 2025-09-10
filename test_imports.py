# Test basic imports work
try:
    import streamlit as st
    import pandas as pd
    import openai
    import pydantic
    print("✅ Core imports working!")
except ImportError as e:
    print(f"❌ Import error: {e}")