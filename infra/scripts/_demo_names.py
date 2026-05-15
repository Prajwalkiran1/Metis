"""Curated lists of Indian names for the Metis demo seed.

Kept small and curated rather than via Faker so the seed is realistic,
deterministic, and adds no dependency. Names lean Bangalore-typical (a
mix of Kannada, Tamil, Telugu, Marathi, Hindi, and a few North-Indian
surnames a real BMSCE roster would contain).

Anything that turns out to be culturally narrow or off-key should be
edited here in one place rather than scattered through the seed.
"""
from __future__ import annotations

import random
from collections.abc import Iterator

MALE_FIRST_NAMES = [
    "Aarav", "Aaditya", "Abhinav", "Abhishek", "Aditya", "Ajay", "Akash",
    "Akhil", "Akshay", "Aman", "Amit", "Anand", "Anirudh", "Ankit", "Ansh",
    "Anuj", "Aravind", "Arjun", "Arnav", "Arun", "Aryan", "Ashish", "Ashwin",
    "Atharv", "Ayush", "Bharath", "Bhavesh", "Chaitanya", "Chetan", "Darshan",
    "Deepak", "Dev", "Dhruv", "Dinesh", "Eshwar", "Gagan", "Ganesh", "Gautam",
    "Girish", "Gopal", "Govind", "Hardik", "Harish", "Harsh", "Harshad",
    "Hemanth", "Hrithik", "Ishaan", "Jagan", "Jai", "Jatin", "Jayanth",
    "Kabir", "Karan", "Karthik", "Kartik", "Keshav", "Krishna", "Kunal",
    "Lakshay", "Lokesh", "Madhav", "Mahesh", "Manish", "Manoj", "Mayank",
    "Mohit", "Mohan", "Naveen", "Neeraj", "Nikhil", "Nitin", "Om", "Pankaj",
    "Pavan", "Piyush", "Prajwal", "Pranav", "Prashant", "Prateek", "Pratham",
    "Pratik", "Praveen", "Puneet", "Raghav", "Rahul", "Raj", "Rajat",
    "Rakesh", "Ram", "Ranveer", "Ravi", "Rishab", "Rishi", "Rohan", "Rohit",
    "Sachin", "Sahil", "Samarth", "Sandeep", "Sanjay", "Sanjeev", "Santosh",
    "Sarthak", "Satish", "Saurav", "Shivam", "Shrey", "Siddharth", "Sourav",
    "Srikanth", "Subramanya", "Sudhakar", "Sumanth", "Sumit", "Sunil",
    "Suraj", "Sushanth", "Tanay", "Tarun", "Tejas", "Tushar", "Uday",
    "Umesh", "Vamsi", "Varun", "Vasanth", "Veer", "Venkatesh", "Vibhav",
    "Vihaan", "Vijay", "Vikas", "Vikram", "Vinay", "Vinod", "Vishal",
    "Vishnu", "Vivek", "Yash", "Yashvant", "Yogesh", "Yuvraj",
]

FEMALE_FIRST_NAMES = [
    "Aadhya", "Aanya", "Aaradhya", "Aishwarya", "Akshara", "Amrita", "Ananya",
    "Anika", "Anjali", "Ankita", "Anushka", "Aparna", "Apoorva", "Archana",
    "Arpita", "Asha", "Avani", "Bhargavi", "Bhavana", "Bhumika", "Chaitra",
    "Chandana", "Charita", "Charvi", "Chitra", "Damini", "Deepa", "Deepika",
    "Devika", "Dhanya", "Diksha", "Divya", "Disha", "Drishya", "Eesha",
    "Esha", "Gauri", "Geetha", "Greeshma", "Hamsa", "Harini", "Harshita",
    "Hema", "Hima", "Indira", "Ishita", "Janani", "Jasmine", "Jayashree",
    "Jyothi", "Kalpana", "Kamini", "Kanchana", "Karuna", "Kashish", "Kavya",
    "Keerthana", "Khushi", "Kiran", "Kriti", "Lakshmi", "Lalitha", "Lavanya",
    "Leela", "Madhuri", "Mahalakshmi", "Mahima", "Maitri", "Malavika",
    "Mallika", "Mamta", "Manasa", "Manisha", "Manjula", "Maya", "Meena",
    "Meera", "Megha", "Mitra", "Mrunalini", "Naina", "Namratha", "Nandini",
    "Navya", "Neha", "Nidhi", "Niharika", "Nikita", "Nirmala", "Nisha",
    "Nithya", "Pallavi", "Pavani", "Pooja", "Poornima", "Prachi", "Pragathi",
    "Prajakta", "Pranati", "Prarthana", "Pratibha", "Pratiksha", "Preeti",
    "Priya", "Priyanka", "Radha", "Rakshitha", "Ramya", "Rashmi", "Reena",
    "Riya", "Rohini", "Roopa", "Ruchi", "Saanvi", "Sahana", "Sakshi",
    "Samhitha", "Samiksha", "Sanika", "Sanjana", "Sapna", "Saraswati",
    "Saritha", "Sarvani", "Shalini", "Shanaya", "Shashi", "Sheetal",
    "Shilpa", "Shivani", "Shobha", "Shradha", "Shreya", "Shruti", "Shubhangi",
    "Smita", "Snehal", "Sonal", "Sonia", "Soumya", "Sowmya", "Sri",
    "Srilatha", "Srinidhi", "Srividya", "Subhashree", "Sudha", "Sukanya",
    "Sumathi", "Sunaina", "Sunita", "Supriya", "Surekha", "Sushma", "Swapna",
    "Swati", "Swetha", "Tanvi", "Tara", "Tejaswini", "Trisha", "Uma",
    "Vaishnavi", "Vandana", "Vanitha", "Vanya", "Varsha", "Vasudha",
    "Vidya", "Vinaya", "Vinitha", "Yamuna", "Yashashri", "Yashika",
]

SURNAMES = [
    "Achar", "Acharya", "Adiga", "Anand", "Bhat", "Bhatt", "Bhandari",
    "Bhardwaj", "Bhargav", "Chakraborty", "Chandra", "Chandrashekhar",
    "Chari", "Chaudhary", "Chitre", "Choudhary", "Damle", "Das", "Dattatreya",
    "Desai", "Deshpande", "Dev", "Devadiga", "Dixit", "Dwivedi", "Gaikwad",
    "Ganesh", "Garg", "Ghosh", "Gowda", "Gupta", "Hegde", "Hosamani", "Iyer",
    "Iyengar", "Jadhav", "Jagannath", "Jain", "Jha", "Joshi", "Kamath",
    "Kannan", "Karanth", "Kashyap", "Katti", "Kaul", "Khanna", "Kini",
    "Kotian", "Krishna", "Krishnamurthy", "Kulkarni", "Kumar", "Kumble",
    "Mahesh", "Malhotra", "Mallya", "Manjunath", "Mehta", "Menon", "Mishra",
    "Mohan", "Mukherjee", "Nadkarni", "Naik", "Naidu", "Nair", "Nanda",
    "Narang", "Narayan", "Narasimhan", "Nayak", "Padmanabhan", "Pai",
    "Pandey", "Pandit", "Patel", "Patil", "Pillai", "Prabhakar", "Prabhu",
    "Pradhan", "Prakash", "Prasad", "Pujari", "Rajan", "Rajagopalan", "Rao",
    "Rai", "Ramaswamy", "Ramachandra", "Ramesh", "Ranganath", "Rangaraj",
    "Rastogi", "Ravindra", "Reddy", "Sahu", "Saini", "Sankaranarayanan",
    "Sarma", "Sastry", "Saxena", "Sen", "Sengupta", "Seshadri", "Sethi",
    "Shankar", "Sharma", "Shenoy", "Shetty", "Shukla", "Singh", "Sinha",
    "Somanath", "Sridhar", "Srinivas", "Srivastava", "Srinivasan", "Subbarao",
    "Subramanian", "Suresh", "Swamy", "Tandon", "Thakur", "Tripathi",
    "Trivedi", "Tyagi", "Udupa", "Upadhyaya", "Venkat", "Venkatesh",
    "Venugopal", "Verma", "Vishwakarma", "Yadav", "Yajnik", "Yelagatla",
]


_TITLES = ("Dr.", "Prof.", "Dr.", "Prof.", "Mr.", "Ms.")


def _next_name(rng: random.Random, pool: list[str]) -> str:
    return rng.choice(pool)


def student_name(rng: random.Random) -> tuple[str, str]:
    """(full_name, gender_hint) — hint is 'm' / 'f' for downstream lookups."""
    if rng.random() < 0.52:
        first = _next_name(rng, MALE_FIRST_NAMES)
        gender = "m"
    else:
        first = _next_name(rng, FEMALE_FIRST_NAMES)
        gender = "f"
    surname = _next_name(rng, SURNAMES)
    return f"{first} {surname}", gender


def parent_name(rng: random.Random, child_surname: str, *, mother: bool) -> str:
    if mother:
        first = _next_name(rng, FEMALE_FIRST_NAMES)
    else:
        first = _next_name(rng, MALE_FIRST_NAMES)
    return f"{first} {child_surname}"


def teacher_name(rng: random.Random) -> str:
    """Faculty name with a small title chance."""
    name, _ = student_name(rng)
    title = _next_name(rng, list(_TITLES))
    return f"{title} {name}"


def iter_names(rng: random.Random) -> Iterator[tuple[str, str]]:
    """Endless stream of (name, gender) — useful for bulk loops."""
    while True:
        yield student_name(rng)


__all__ = [
    "MALE_FIRST_NAMES",
    "FEMALE_FIRST_NAMES",
    "SURNAMES",
    "student_name",
    "parent_name",
    "teacher_name",
    "iter_names",
]
