import streamlit as st
from supabase import create_client, Client

# 1. Initialize the connection (do NOT name this variable 'supabase' 
# if you want to avoid confusion with the 'import supabase' module name)
url = st.secrets["SUPABASE_URL"]
key = st.secrets["SUPABASE_KEY"]

# This creates the Client object that HAS the .table() method
supabase_client: Client = create_client(url, key)

# 2. Use the client object, not the module
# Use supabase_client.table() instead of supabase.table()
role = "Admin" # Example role
response = supabase_client.table("complaints").select("*").eq("category", role).execute()

# 3. Access your data
st.write(response.data)