#!/usr/bin/env python3
# Copyright 2024
# Directory: yt-rag/test_setup.py

"""
Test script to verify RAG backend setup is working correctly.
Run this after completing the setup steps.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the app directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

async def test_setup():
    """Test the complete RAG setup."""
    print("🧪 Testing RAG Backend Setup...")
    print("=" * 50)
    
    try:
        # Test 1: Import modules
        print("1️⃣  Testing imports...")
        from app.core.config import get_settings
        from app.core.database import db
        from app.services.rag import rag_service
        print("   ✅ All modules imported successfully")
        
        # Test 2: Check configuration
        print("\n2️⃣  Testing configuration...")
        settings = get_settings()
        
        # Check required environment variables
        required_vars = [
            'SUPABASE_URL', 'SUPABASE_ANON_KEY', 'SUPABASE_SERVICE_ROLE_KEY',
            'OPENAI_API_KEY'
        ]
        
        missing_vars = []
        for var in required_vars:
            if not os.getenv(var) or os.getenv(var) == f"your_{var.lower()}_here":
                missing_vars.append(var)
        
        if missing_vars:
            print(f"   ❌ Missing environment variables: {', '.join(missing_vars)}")
            print("   💡 Please update your .env file with real API keys")
            return False
        
        print("   ✅ Environment variables configured")
        print(f"   📊 Using embedding model: {settings.openai_embed_model}")
        print(f"   🤖 Using chat model: {settings.openai_chat_model}")
        print(f"   🔗 Using AI provider: {settings.ai_provider}")
        
        # Test 3: Database connection
        print("\n3️⃣  Testing database connection...")
        await db.connect()
        health = await db.health_check()
        
        if not health:
            print("   ❌ Database connection failed")
            print("   💡 Check your Supabase credentials and ensure the project is active")
            return False
        
        print("   ✅ Database connection successful")
        
        # Test 4: Schema validation
        print("\n4️⃣  Testing database schema...")
        await db.initialize_schema()
        print("   ✅ Database schema validated")
        
        # Test 5: Seeding documents
        print("\n5️⃣  Testing document seeding...")
        seeded = await rag_service.seed_documents()

        if seeded.inserted == 0:
            print("   ⚠️  No document chunks inserted")
        else:
            print(f"   ✅ Seeded {seeded.inserted} document chunks, removed {seeded.removed} old ones")
        
        # Test 6: RAG query
        print("\n6️⃣  Testing RAG query...")
        test_query = "Who is Kai?"
        result = await rag_service.answer_query(test_query)
        
        if not result['text'] or "error" in result['text'].lower():
            print("   ❌ RAG query failed")
            print(f"   🔍 Response: {result['text'][:100]}...")
            return False
        
        print("   ✅ RAG query successful!")
        print(f"   📝 Answer: {result['text'][:100]}...")
        print(f"   📚 Citations: {result['citations']}")
        print(f"   ⏱️  Latency: {result['debug']['latency_ms']}ms")
        
        # Cleanup
        await db.disconnect()
        
        print("\n🎉 ALL TESTS PASSED!")
        print("=" * 50)
        print("✅ Your RAG backend is fully functional!")
        print("🚀 You can now start the server with: uvicorn main:app --reload --port 8000")
        print("📚 Visit http://localhost:8000/docs for interactive API documentation")
        
        return True
        
    except ImportError as e:
        print(f"   ❌ Import error: {e}")
        print("   💡 Make sure you've installed dependencies: pip install -r requirements.txt")
        return False
        
    except Exception as e:
        print(f"   ❌ Setup test failed: {e}")
        print("   💡 Check the error message above and refer to QUICKSTART.md")
        return False


async def main():
    """Main test function."""
    print("🔧 RAG Backend Setup Verification")
    print("This will test your complete setup without starting the server.\n")
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    success = await test_setup()
    
    if success:
        print("\n🎯 Next Steps:")
        print("1. Start the server: uvicorn main:app --reload --port 8000")
        print("2. Test the health endpoint: curl http://localhost:8000/healthz")
        print("3. Ask a question: curl -X POST http://localhost:8000/answer -H 'Content-Type: application/json' -d '{\"query\":\"Who is Kai?\"}'")
        print("4. Visit the interactive docs: http://localhost:8000/docs")
        sys.exit(0)
    else:
        print("\n❌ Setup incomplete. Please fix the issues above and try again.")
        print("📖 Refer to QUICKSTART.md for detailed setup instructions.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
