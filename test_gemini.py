import google.generativeai as genai
genai.configure(api_key='AIzaSyBuaN3NrcOg63zZC9pDDl6kJ1y5d3frM5c')
model = genai.GenerativeModel('gemini-2.5-flash')
with open('static/img/vodafone_logo.png', 'rb') as f:
    data = f.read()
part = {'mime_type': 'image/png', 'data': data}
response = model.generate_content(['Hello', part])
print(response.text)
