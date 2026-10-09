from ..domain import HealthQuestion

HEALTH_QUESTIONS: list[HealthQuestion] = [
    HealthQuestion(id="q1", text="Czy lekarz stwierdził chorobę serca lub zalecił aktywność fizyczną wyłącznie pod nadzorem?"),
    HealthQuestion(id="q2", text="Czy podczas wysiłku pojawia się ból w klatce piersiowej?"),
    HealthQuestion(id="q3", text="Czy w ostatnim miesiącu wystąpił ból w klatce piersiowej w spoczynku?"),
    HealthQuestion(
        id="q4",
        text="Czy w ciągu ostatnich 12 miesięcy wystąpiła utrata przytomności lub zawroty głowy z utratą równowagi?",
    ),
    HealthQuestion(
        id="q5",
        text="Czy występuje obecnie kontuzja albo dolegliwość kości, stawów lub mięśni, która nasila się przy bieganiu?",
    ),
    HealthQuestion(id="q6", text="Czy przyjmowane są leki na nadciśnienie lub chorobę serca?"),
    HealthQuestion(
        id="q7",
        text="Czy występuje obecnie choroba, infekcja z gorączką albo inny powód, by nie trenować?",
    ),
]

MEDICAL_DISCLAIMER = (
    "System nie udziela porad medycznych. Plany mają charakter informacyjny i nie zastępują konsultacji "
    "z lekarzem lub trenerem. W razie wątpliwości co do stanu zdrowia należy skonsultować się z lekarzem "
    "przed rozpoczęciem treningu."
)
