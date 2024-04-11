import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv() 

client = OpenAI(api_key = os.environ.get("OPENAI_API_KEY"))

def chatbot(userinput):
    response = client.chat.completions.create(
    model="gpt-4-turbo-preview",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": userinput},
    ]
    )

    print(f'{response.usage.prompt_tokens} prompt tokens used.')
    return response.choices[0].message.content

user_input = ""
while user_input != "exit":
    user_input = input("Enter your message: ")
    if user_input != "exit":
        print(f"Chatbot: {chatbot(user_input)}")
