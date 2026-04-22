import google.generativeai as genai
genai.configure(api_key='AIzaSyBpW4owyc2QbNvlHeS27l0RhOts8bKniJU')
model = genai.GenerativeModel('gemini-2.5-flash')
with open('static/img/vodafone_logo.png', 'rb') as f:
    data = f.read()
part = {'mime_type': 'image/png', 'data': data}
response = model.generate_content(['Hello', part])
print(response.text)
