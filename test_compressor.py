from dalal_ai.core.context_compressor import ContextCompressor

def test_compressor():
    history = [
        {"role": "user", "content": "What is the capital of France?"},
        {"role": "assistant", "content": "The capital of France is Paris."},
        {"role": "user", "content": "What about Italy?"},
        {"role": "assistant", "content": "The capital of Italy is Rome."},
        {"role": "user", "content": "Tell me a joke."},
        {"role": "assistant", "content": "Why did the chicken cross the road? To get to the other side."},
        {"role": "user", "content": "Tell me about cars."},
        {"role": "assistant", "content": "Cars are vehicles with four wheels."},
        {"role": "user", "content": "Tell me about planes."},
        {"role": "assistant", "content": "Planes are vehicles that fly."},
        {"role": "user", "content": "Tell me about boats."},
        {"role": "assistant", "content": "Boats are vehicles that float."},
        {"role": "user", "content": "What is the capital of Spain?"},
        {"role": "assistant", "content": "The capital of Spain is Madrid."}
    ]
    query = "Tell me about capitals."
    
    compressor = ContextCompressor(recent_count=2, chunk_size=2, max_tokens=100)
    result = compressor.build_context(history, query)
    
    print("Test successful! Output messages:")
    for msg in result:
        print(f"  [{msg['role'].upper()}] {msg['content']}")

if __name__ == "__main__":
    test_compressor()
