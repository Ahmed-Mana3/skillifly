from google import genai
from google.genai import types

client = genai.Client(api_key='AIzaSyBuaN3NrcOg63zZC9pDDl6kJ1y5d3frM5c')

with open('static/img/vodafone_logo.png', 'rb') as f:
    data = f.read()

image_part = types.Part.from_bytes(data=data, mime_type='image/png')
response = client.models.generate_content(
    model='gemini-2.0-flash',
    contents=['Hello', image_part]
)
print(response.text)
