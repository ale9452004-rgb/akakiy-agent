def process_request(request):
    if not request:
        return {
            "message": "Запрос пуст.",
            "answer": "Пустой запрос."
        }

    return {
        "message": "Запрос получен.",
        "answer": "OK"
    }
