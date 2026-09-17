def process_request(request):
    if not request:
        return {
            "message": "Пустой запрос.",
            "answer": "Пустой запрос."
        }

    return {
        "message": "Запрос получен.",
        "answer": "OK"
    }
