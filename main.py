from infrastructure.composition import TelegramAdapterApplicationFactory


app = TelegramAdapterApplicationFactory.create_fastapi_app()
