import os
import psycopg2
from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd
from datetime import datetime

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
#db = SQL("sqlite:///finance.db")
db = SQL(os.environ.get("DATABASE_URL") or "sqlite:///finance.db")

#db.execute("PRAGMA foreign_keys = ON;")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    try:
        os.environ["API_KEY"] = 'pk_6e667ff3d75547cf9700f709bc349faf'
    except:
        raise RuntimeError("API_KEY not set")

@app.route("/admin", methods=["GET", "POST"])
@login_required
def admin():
    """Show admin panel"""
    if request.method == "GET":
        accounts = db.execute("SELECT id, username FROM users ORDER BY id ASC;")

        return render_template("admin.html", accounts=accounts)

    userid = request.form.get("submit")
    user = db.execute("SELECT username FROM users where id = :id", id = userid)[0]
    db.execute("DELETE FROM users WHERE id = :id", id = userid)

    flash("Deleted {0} from database".format(user["username"]))
    accounts = db.execute("SELECT id, username FROM users ORDER BY id ASC;")

    return render_template("admin.html", accounts=accounts)

@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    userid = session["user_id"]
    stocks = db.execute("""
        SELECT symbol, SUM(shares) AS shares, SUM(total) AS total
        FROM transactions WHERE id = :user_id
        GROUP BY symbol
        HAVING SUM(shares) > 0;
        """, user_id = userid)

    user = db.execute("""
        SELECT *
        FROM users
        WHERE id = :user_id
        """, user_id = userid)[0]

    if not stocks:
        return render_template("index.html", username = user["username"], message = "Empty")

    portfoliototal = 0
    for stock in stocks:
        quote = lookup(stock["symbol"])
        value = stock["shares"] * quote["price"]
        portfoliototal += value
        stock.update({"total": usd(value)})
        stock.update({"price": usd(quote["price"])})
    grandtotal = portfoliototal + user["cash"]

    return render_template("index.html", rows=stocks, portfolio = usd(portfoliototal), grandtotal = usd(grandtotal), username = user["username"], cash = usd(user["cash"]))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "GET":
        return render_template("buy.html")

    symbol = request.form.get("quote")
    quote = lookup(symbol)
    if not quote:
        return apology("Not Found", 403)

    shares = int(request.form.get("shares"))
    total = quote["price"] * shares
    userid = session["user_id"]
    balance = db.execute("""
        SELECT cash
        FROM users
        WHERE id = :user_id
        """, user_id=userid)[0]["cash"]

    if balance < total:
        return apology("Insufficient funds", 403)

    # Proceed with transaction
    cashLeft = balance - total
    db.execute("""
        UPDATE users
        SET cash = :newBalance
        WHERE id = :user_id
        """, newBalance = cashLeft, user_id=userid)

    db.execute("""
        CREATE TABLE IF NOT EXISTS transactions
        (id INTEGER NOT NULL,
        status TEXT NOT NULL,
        symbol TEXT NOT NULL,
        company_name  TEXT NOT NULL,
        shares INTEGER NOT NULL,
        price NUMERIC NOT NULL,
        total NUMERIC NOT NULL,
        date TEXT NOT NULL,
        CONSTRAINT fk_users,
        FOREIGN KEY(id)
        REFERENCES users(id)
        ON DELETE CASCADE
        );
        """)

    date = datetime.now().strftime("%m/%d/%Y %H:%M:%S")
    db.execute("""
        INSERT INTO transactions (id, status, symbol, company_name, shares, price, total, date)
        VALUES(?,?,?,?,?,?,?,?)
        """, userid, "Bought", symbol, quote["name"], shares, quote["price"], total, date)

    flash("Bought {0} shares of {1}".format(shares, quote["name"]))

    return redirect("/")

@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    userid = session["user_id"]
    transactions = db.execute("""
        SELECT *
        FROM transactions WHERE id = :user_id
        """, user_id = userid)

    user = db.execute("""
        SELECT *
        FROM users
        WHERE id = :user_id
        """, user_id = userid)[0]

    if not transactions:
        return render_template("history.html", username = user["username"], message = "No transaction history")

    for txn in transactions:
        txn.update({"total": usd(txn["total"])})
        txn.update({"price": usd(txn["price"])})

    return render_template("history.html", rows=transactions, username = user["username"], cash = usd(user["cash"]))

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    if request.method == "GET":
        return render_template("quote.html")

    else:
        """Get stock quote."""
        symbol = request.form.get("quote")
        quote = lookup(symbol)
        if not quote:
            return apology("Not Found", 403)

        return render_template("quoted.html", quote=quote)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "GET":
        return render_template("register.html")

    # User reached route via POST (as by submitting a form via POST)
    else:

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        password = request.form.get("password")
        if not password:
            return apology("must provide password", 403)

        elif not (request.form.get("password") == request.form.get("password-check")):
            #return render_template("register.html")
             return apology("passwords do not match", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username not taken
        if len(rows) != 0:
            return apology("Username has already been taken", 403)

        hashpw = generate_password_hash(password)
        # Insert new user into database
        newUser = db.execute("INSERT INTO users (username, hash) values(:username, :hash)",
                    username = request.form.get("username"), hash = hashpw)

        # Remember which user has logged in
        session["user_id"] = newUser

        # Redirect user to home page
        return redirect("/")

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    userid = session["user_id"]

    if request.method == "GET":
        symbol_dict = db.execute("SELECT symbol FROM transactions WHERE id = :id GROUP BY symbol ORDER BY symbol ASC", id = userid)

        return render_template("sell.html", symbols=symbol_dict)

    symbol = request.form.get("symbol")
    quote = lookup(symbol)
    if not quote:
        return apology("Not Found", 403)

    stocks = db.execute("""
        SELECT symbol, SUM(shares) AS shares, SUM(total) AS total
        FROM transactions
        WHERE id = :user_id AND symbol = :symbol
        GROUP BY symbol
        """, user_id = userid, symbol=symbol)[0]

    if not stocks:
        return apology("You do not own any shares", 403)

    sharesToSell = int(request.form.get("shares"))
    shares = int(stocks["shares"])
    if sharesToSell > shares:
        return apology("Exceeds number of shares owned", 403)

    user = db.execute("""
        SELECT *
        FROM users
        WHERE id = :user_id;
        """, user_id = userid)[0]

    total = quote["price"] * sharesToSell
    sharesLeft = shares - sharesToSell
    cash = user["cash"] + total

    date = datetime.now().strftime("%m/%d/%Y %H:%M:%S")
    db.execute("""
        INSERT INTO transactions (id, status, symbol, company_name, shares, price, total, date)
        VALUES(?,?,?,?,?,?,?,?)
        """, userid, "Sold", symbol, quote["name"], -sharesToSell, quote["price"], -total, date)

    db.execute("""
        UPDATE users
        SET cash = :newBalance
        WHERE id = :user_id;
        """, newBalance = cash, user_id=userid)

    flash("Sold!")

    #return render_template("bought.html", quote=quote, shares=shares, total=total, balance=cashLeft)
    return redirect("/")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)