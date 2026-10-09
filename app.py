from pathlib import Path
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st


st.set_page_config(page_title="Shop Manager", page_icon="🛍️", layout="wide")
DB_PATH = Path(__file__).parent / "shop_data.db"
SAMPLE_PATH = Path(__file__).parent / "data" / "sample_transactions.csv"


def connect():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT DEFAULT '', phone TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT DEFAULT '', phone TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            sku TEXT NOT NULL UNIQUE, unit_cost REAL NOT NULL DEFAULT 0, selling_price REAL NOT NULL DEFAULT 0,
            stock INTEGER NOT NULL DEFAULT 0, low_stock_level INTEGER NOT NULL DEFAULT 5,
            active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
        );
        CREATE TABLE IF NOT EXISTS transactions(
            id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('sale','purchase')), product_id INTEGER NOT NULL REFERENCES products(id),
            quantity INTEGER NOT NULL CHECK(quantity > 0), unit_price REAL NOT NULL, unit_cost REAL NOT NULL,
            customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
            supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
            transaction_date TEXT NOT NULL, note TEXT DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(transaction_date);
        """)
        if con.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
            con.executemany("INSERT INTO categories(name) VALUES(?)", [(x,) for x in ["Electronics", "Home", "Beauty", "Fashion", "Other"]])
        if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            cats = {r["name"]: r["id"] for r in con.execute("SELECT id,name FROM categories")}
            examples = [("Wireless Headphones", "ELEC-001", "Electronics", 24, 59.99, 24, 5), ("Desk Lamp", "HOME-001", "Home", 18, 39.99, 18, 4), ("Face Moisturizer", "BEAU-001", "Beauty", 7, 19.50, 7, 8), ("Cotton T-shirt", "FASH-001", "Fashion", 9, 24.99, 9, 6)]
            con.executemany("INSERT INTO products(name,sku,category_id,unit_cost,selling_price,stock,low_stock_level) VALUES(?,?,?,?,?,?,?)", [(n,s,cats[cat],cost,price,stock,level) for n,s,cat,cost,price,stock,level in examples])


def rows(sql, args=()):
    with connect() as con:
        return pd.read_sql_query(sql, con, params=args)


def options(table):
    return rows(f"SELECT id,name FROM {table} ORDER BY name")


def money(value):
    return f"${value:,.2f}"


init_db()
st.title("🛍️ Shop Manager")
st.caption("A simple place to manage products, stock, customers, suppliers, and sales.")

with st.sidebar:
    st.header("Shop Manager")
    page = st.radio("Go to", ["Dashboard", "Products & categories", "Record a sale", "Record a purchase", "Customers & suppliers", "Customer analysis"], label_visibility="collapsed")
    st.divider()
    st.caption("Your shop data is saved on this computer in a local SQLite database.")

if page == "Dashboard":
    tx = rows("SELECT * FROM transactions")
    products = rows("SELECT p.*, c.name AS category FROM products p LEFT JOIN categories c ON c.id=p.category_id WHERE active=1")
    sales = tx[tx.kind == "sale"] if not tx.empty else tx
    purchases = tx[tx.kind == "purchase"] if not tx.empty else tx
    revenue = float((sales.quantity * sales.unit_price).sum()) if not sales.empty else 0
    purchase_total = float((purchases.quantity * purchases.unit_cost).sum()) if not purchases.empty else 0
    profit = float((sales.quantity * (sales.unit_price - sales.unit_cost)).sum()) if not sales.empty else 0
    a,b,c,d = st.columns(4)
    a.metric("Sales revenue", money(revenue))
    b.metric("Purchases", money(purchase_total))
    c.metric("Gross profit", money(profit), help="Sales revenue minus the recorded cost of the items sold.")
    d.metric("Sales made", f"{len(sales):,}")
    st.subheader("Stock to check")
    low = products[products.stock <= products.low_stock_level].sort_values("stock")
    if low.empty:
        st.success("Everything is stocked above its low-stock level.")
    else:
        st.warning(f"{len(low)} product(s) are at or below their low-stock level.")
        st.dataframe(low[["name","sku","category","stock","low_stock_level"]].rename(columns={"name":"Product","sku":"SKU","category":"Category","stock":"In stock","low_stock_level":"Alert at"}), hide_index=True, use_container_width=True)
    if not tx.empty:
        tx["date"] = pd.to_datetime(tx.transaction_date)
        month_sales = tx[tx.kind == "sale"].assign(revenue=lambda x: x.quantity*x.unit_price).set_index("date").resample("MS").revenue.sum().rename("Revenue").reset_index()
        if not month_sales.empty:
            st.plotly_chart(px.line(month_sales, x="date", y="Revenue", markers=True, title="Sales revenue over time"), use_container_width=True)
        with st.expander("Recent activity"):
            recent = rows("SELECT t.transaction_date AS Date,t.kind AS Type,p.name AS Product,t.quantity AS Quantity,t.unit_price AS 'Unit price',t.note AS Note FROM transactions t JOIN products p ON p.id=t.product_id ORDER BY t.id DESC LIMIT 12")
            st.dataframe(recent, hide_index=True, use_container_width=True)
    else:
        st.info("Your dashboard will fill in as you record purchases and sales.")

elif page == "Products & categories":
    st.subheader("Products & categories")
    cat = options("categories")
    with st.expander("Add a category", expanded=False):
        with st.form("add_category"):
            name = st.text_input("Category name", placeholder="e.g. Accessories")
            if st.form_submit_button("Add category"):
                if name.strip():
                    try:
                        with connect() as con: con.execute("INSERT INTO categories(name) VALUES(?)", (name.strip(),))
                        st.success("Category added."); st.rerun()
                    except sqlite3.IntegrityError: st.error("That category already exists.")
                else: st.error("Enter a category name.")
    with st.expander("Rename or remove a category"):
        if cat.empty: st.info("Add a category first.")
        else:
            selected_cat = st.selectbox("Choose category", cat.id, format_func=lambda x: cat.loc[cat.id == x, "name"].iloc[0], key="cat_edit")
            with st.form("edit_category"):
                new_name = st.text_input("New name", value=cat.loc[cat.id == selected_cat,"name"].iloc[0])
                if st.form_submit_button("Save category name"):
                    try:
                        with connect() as con: con.execute("UPDATE categories SET name=? WHERE id=?", (new_name.strip(),selected_cat))
                        st.success("Category updated."); st.rerun()
                    except sqlite3.IntegrityError: st.error("A category with that name already exists.")
            if st.button("Delete category", key="delete_cat"):
                with connect() as con: con.execute("DELETE FROM categories WHERE id=?", (selected_cat,))
                st.info("Category removed. Products in it are now uncategorized."); st.rerun()
    st.divider()
    st.markdown("#### Add a product")
    cat = options("categories")
    with st.form("add_product"):
        x1,x2,x3 = st.columns(3)
        pname=x1.text_input("Product name"); sku=x2.text_input("SKU / product code"); category=x3.selectbox("Category", [None]+cat.id.tolist(), format_func=lambda x: "Uncategorized" if x is None else cat.loc[cat.id==x,"name"].iloc[0])
        x1,x2,x3,x4 = st.columns(4)
        cost=x1.number_input("Cost per item ($)",min_value=0.0,step=1.0); price=x2.number_input("Selling price ($)",min_value=0.0,step=1.0); stock=x3.number_input("Starting stock",min_value=0,step=1); threshold=x4.number_input("Low-stock alert at",min_value=0,step=1,value=5)
        if st.form_submit_button("Add product"):
            if not pname.strip() or not sku.strip(): st.error("Enter both a product name and SKU.")
            else:
                try:
                    with connect() as con: con.execute("INSERT INTO products(name,sku,category_id,unit_cost,selling_price,stock,low_stock_level) VALUES(?,?,?,?,?,?,?)", (pname.strip(),sku.strip(),category,cost,price,stock,threshold))
                    st.success("Product added."); st.rerun()
                except sqlite3.IntegrityError: st.error("That SKU is already in use.")
    products=rows("SELECT p.*,c.name AS category FROM products p LEFT JOIN categories c ON c.id=p.category_id ORDER BY p.name")
    st.markdown("#### Product list")
    if not products.empty:
        st.dataframe(products[["name","sku","category","unit_cost","selling_price","stock","low_stock_level"]].rename(columns={"name":"Product","sku":"SKU","category":"Category","unit_cost":"Cost","selling_price":"Price","stock":"In stock","low_stock_level":"Alert at"}).style.format({"Cost":"${:,.2f}","Price":"${:,.2f}"}), hide_index=True,use_container_width=True)
        ids=products.id.tolist()
        chosen=st.selectbox("Choose a product to edit",ids,format_func=lambda i: f"{products.loc[products.id==i,'name'].iloc[0]} ({products.loc[products.id==i,'sku'].iloc[0]})")
        item=products[products.id==chosen].iloc[0]
        cat=options("categories")
        with st.form("edit_product"):
            n1,n2,n3=st.columns(3)
            ename=n1.text_input("Product name",value=item["name"]); esku=n2.text_input("SKU",value=item["sku"]); ecat=n3.selectbox("Category",[None]+cat.id.tolist(),index=([None]+cat.id.tolist()).index(item["category_id"]),format_func=lambda x:"Uncategorized" if x is None else cat.loc[cat.id==x,"name"].iloc[0])
            n1,n2,n3=st.columns(3)
            ecost=n1.number_input("Cost per item ($)",min_value=0.0,value=float(item.unit_cost),step=1.0); eprice=n2.number_input("Selling price ($)",min_value=0.0,value=float(item.selling_price),step=1.0); ethresh=n3.number_input("Low-stock alert at",min_value=0,value=int(item.low_stock_level),step=1)
            if st.form_submit_button("Save product details"):
                try:
                    with connect() as con: con.execute("UPDATE products SET name=?,sku=?,category_id=?,unit_cost=?,selling_price=?,low_stock_level=? WHERE id=?",(ename.strip(),esku.strip(),ecat,ecost,eprice,ethresh,chosen))
                    st.success("Product details saved."); st.rerun()
                except sqlite3.IntegrityError: st.error("That SKU is already in use.")
        if st.button("Delete selected product",type="secondary"):
            with connect() as con:
                if con.execute("SELECT COUNT(*) FROM transactions WHERE product_id=?",(chosen,)).fetchone()[0]:
                    con.execute("UPDATE products SET active=0 WHERE id=?",(chosen,)); st.info("Product hidden from the product list. Its transaction history is preserved.")
                else:
                    con.execute("DELETE FROM products WHERE id=?",(chosen,)); st.success("Product deleted.")
            st.rerun()

elif page in ("Record a sale","Record a purchase"):
    is_sale=page=="Record a sale"
    st.subheader("Record a sale" if is_sale else "Record a purchase")
    st.caption("Stock is updated automatically when you save this transaction.")
    products=rows("SELECT id,name,sku,stock,unit_cost,selling_price FROM products WHERE active=1 ORDER BY name")
    people=options("customers" if is_sale else "suppliers")
    if products.empty: st.info("Add a product before recording a transaction.")
    else:
        with st.form("transaction_form"):
            prod=st.selectbox("Product",products.id,format_func=lambda i:f"{products.loc[products.id==i,'name'].iloc[0]} · In stock: {products.loc[products.id==i,'stock'].iloc[0]}")
            item=products[products.id==prod].iloc[0]
            person=st.selectbox("Customer" if is_sale else "Supplier",[None]+people.id.tolist(),format_func=lambda i:"Walk-in customer" if is_sale and i is None else "Choose later" if i is None else people.loc[people.id==i,"name"].iloc[0])
            qcol,pcol=st.columns(2)
            qty=qcol.number_input("Quantity",min_value=1,step=1,max_value=int(item.stock) if is_sale and item.stock>0 else None)
            price=pcol.number_input("Selling price per item ($)" if is_sale else "Cost per item ($)",min_value=0.0,value=float(item.selling_price if is_sale else item.unit_cost),step=1.0)
            date=st.date_input("Date")
            note=st.text_input("Note (optional)",placeholder="e.g. Order number or delivery note")
            submitted=st.form_submit_button("Save sale and update stock" if is_sale else "Save purchase and update stock",type="primary")
        if submitted:
            if is_sale and qty>int(item.stock): st.error(f"Only {int(item.stock)} item(s) are currently in stock.")
            else:
                try:
                    with connect() as con:
                        con.execute("INSERT INTO transactions(kind,product_id,quantity,unit_price,unit_cost,customer_id,supplier_id,transaction_date,note) VALUES(?,?,?,?,?,?,?,?,?)",("sale" if is_sale else "purchase",prod,qty,price,float(item.unit_cost if is_sale else price),person if is_sale else None,person if not is_sale else None,date.isoformat(),note.strip()))
                        con.execute("UPDATE products SET stock=stock+? WHERE id=?",(-qty if is_sale else qty,prod))
                    st.success(("Sale" if is_sale else "Purchase")+" saved and stock updated."); st.rerun()
                except sqlite3.Error as exc: st.error(f"Could not save transaction: {exc}")

elif page == "Customers & suppliers":
    st.subheader("Customers & suppliers")
    ctab,stab=st.tabs(["Customers","Suppliers"])
    for table, label, tab in [("customers","customer",ctab),("suppliers","supplier",stab)]:
        with tab:
            listing=options(table)
            with st.expander(f"Add a {label}",expanded=listing.empty):
                with st.form(f"add_{table}"):
                    nm=st.text_input(f"{label.title()} name"); email=st.text_input("Email (optional)"); phone=st.text_input("Phone (optional)")
                    if st.form_submit_button(f"Add {label}"):
                        if not nm.strip(): st.error("Enter a name.")
                        else:
                            with connect() as con: con.execute(f"INSERT INTO {table}(name,email,phone) VALUES(?,?,?)",(nm.strip(),email.strip(),phone.strip()))
                            st.success(f"{label.title()} added."); st.rerun()
            data=rows(f"SELECT id,name,email,phone FROM {table} ORDER BY name")
            if data.empty: st.info(f"No {label}s added yet.")
            else:
                st.dataframe(data.drop(columns="id").rename(columns={"name":"Name","email":"Email","phone":"Phone"}),hide_index=True,use_container_width=True)
                pick=st.selectbox(f"Choose {label} to edit",data.id,format_func=lambda i:data.loc[data.id==i,"name"].iloc[0],key=f"pick_{table}")
                person=data[data.id==pick].iloc[0]
                with st.form(f"edit_{table}"):
                    nm=st.text_input("Name",value=person.name); email=st.text_input("Email",value=person.email); phone=st.text_input("Phone",value=person.phone)
                    if st.form_submit_button("Save details"):
                        with connect() as con: con.execute(f"UPDATE {table} SET name=?,email=?,phone=? WHERE id=?",(nm.strip(),email.strip(),phone.strip(),pick))
                        st.success("Details saved."); st.rerun()
                if st.button(f"Delete {label}",key=f"del_{table}"):
                    with connect() as con: con.execute(f"DELETE FROM {table} WHERE id=?",(pick,))
                    st.info(f"{label.title()} removed. Past transactions remain saved."); st.rerun()

else:
    st.subheader("Customer analysis")
    st.caption("Explore customer orders and buying patterns. Upload your own transaction CSV or use the included example.")
    uploaded=st.file_uploader("Upload transaction CSV",type=["csv"],help="Required: order_id, customer_id, order_date, product_category, quantity, unit_price, country")
    try:
        raw=pd.read_csv(uploaded) if uploaded else pd.read_csv(SAMPLE_PATH)
        required={"order_id","customer_id","order_date","product_category","quantity","unit_price","country"}
        missing=required-set(raw.columns)
        if missing: raise ValueError("Missing columns: "+", ".join(sorted(missing)))
        df=raw.copy(); df["order_date"]=pd.to_datetime(df.order_date,errors="coerce"); df["quantity"]=pd.to_numeric(df.quantity,errors="coerce"); df["unit_price"]=pd.to_numeric(df.unit_price,errors="coerce")
        df=df.dropna(subset=["order_id","customer_id","order_date","quantity","unit_price"]); df=df[(df.quantity>0)&(df.unit_price>=0)]; df["revenue"]=df.quantity*df.unit_price
        if df.empty: raise ValueError("No valid rows found.")
        bounds=st.date_input("Analysis date range",(df.order_date.min().date(),df.order_date.max().date()),min_value=df.order_date.min().date(),max_value=df.order_date.max().date())
        if isinstance(bounds,tuple) and len(bounds)==2: df=df[(df.order_date>=pd.Timestamp(bounds[0]))&(df.order_date<pd.Timestamp(bounds[1])+pd.Timedelta(days=1))]
        order=df.groupby("order_id").agg(customer_id=("customer_id","first"),order_date=("order_date","first"),revenue=("revenue","sum"))
        customers=df.groupby("customer_id").agg(orders=("order_id","nunique"),revenue=("revenue","sum"),last_order=("order_date","max"))
        k1,k2,k3,k4=st.columns(4); k1.metric("Revenue",money(df.revenue.sum())); k2.metric("Orders",f"{len(order):,}"); k3.metric("Customers",f"{len(customers):,}"); k4.metric("Repeat customer rate",f"{(customers.orders>1).mean()*100:.1f}%")
        left,right=st.columns(2)
        with left:
            monthly=order.set_index("order_date").resample("MS").revenue.sum().rename("Revenue").reset_index()
            st.plotly_chart(px.line(monthly,x="order_date",y="Revenue",markers=True,title="Monthly revenue"),use_container_width=True)
        with right:
            cats=df.groupby("product_category",as_index=False).revenue.sum().sort_values("revenue",ascending=False)
            st.plotly_chart(px.bar(cats,x="product_category",y="revenue",title="Revenue by category"),use_container_width=True)
        top_customers=customers.nlargest(10,"revenue").reset_index()
        top_customers["customer_id"]=top_customers["customer_id"].astype(str)
        top_customers=top_customers.sort_values("revenue",ascending=True)
        st.plotly_chart(px.bar(top_customers,x="revenue",y="customer_id",orientation="h",title="Top customers by spend",labels={"revenue":"Spend","customer_id":"Customer ID"}),use_container_width=True)
        st.markdown("#### Customer segments")
        st.caption("RFM groups use recency (how recently they bought), frequency (number of orders), and monetary value (total spend). Scores are relative to this date range.")
        as_of=df.order_date.max()+pd.Timedelta(days=1)
        rfm=df.groupby("customer_id").agg(recency=("order_date",lambda s:(as_of-s.max()).days),frequency=("order_id","nunique"),monetary=("revenue","sum"))
        for col,ascending in [("R",False),("F",True),("M",True)]:
            source={"R":"recency","F":"frequency","M":"monetary"}[col]
            rfm[col]=pd.qcut(rfm[source].rank(method="first",ascending=ascending),4,labels=False).astype(int)+1
        rfm["Segment"]="Needs attention"; rfm.loc[(rfm.R>=3)&(rfm.F>=3)&(rfm.M>=3),"Segment"]="Champions"; rfm.loc[(rfm.R>=3)&(rfm.F>=2)&(rfm.Segment!="Champions"),"Segment"]="Loyal customers"; rfm.loc[(rfm.R<=2)&(rfm.F>=3),"Segment"]="At risk"
        summary=rfm.groupby("Segment").agg(Customers=("recency","size"),Revenue=("monetary","sum")).reset_index()
        st.plotly_chart(px.pie(summary,names="Segment",values="Customers",hole=.4,title="Customer mix"),use_container_width=True)
        st.dataframe(summary.style.format({"Revenue":"${:,.2f}"}),hide_index=True,use_container_width=True)
        st.download_button("Download customer segments",rfm.reset_index().to_csv(index=False).encode(),"customer_segments.csv","text/csv")
    except Exception as exc: st.error(f"Could not analyze this file: {exc}")
