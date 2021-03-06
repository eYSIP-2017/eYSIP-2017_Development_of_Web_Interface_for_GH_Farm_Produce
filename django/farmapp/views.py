import csv
import datetime
import os

from django.conf import settings
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import transaction
from django.db.models import F,Q
from django.db.models import Sum,Avg,Min
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import render, HttpResponseRedirect
from django.template.defaulttags import register
from django.views.decorators.cache import cache_control
from farmapp.models import User, Produce, Machine, Inventory, Crop, Cart, Cart_session, Order, Alert, Review
from graphos.renderers.morris import BarChart
from graphos.sources.simple import SimpleDataSource
from django.contrib.auth import authenticate, login, logout

from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from .forms import LoginForm, SignUpForm, AnalyticsForm, CropAnalyticsForm, InventoryForm, ProduceForm, UserForm

# Function to handle login and signup of user
# returns redirect, login form, signup form
def handle_login_signup(request):
    print("CALLED HANDLE")
    loginform = LoginForm()
    signupform = SignUpForm()

    # If user is already logged in.
    if request.user.is_authenticated:
        if request.user.user_type.upper() == "PRODUCER":
            return HttpResponseRedirect('/producer/home/'), loginform, signupform
        else:
            return HttpResponseRedirect('/home/'), loginform, signupform

    # Handling the form submitted
    if request.method == "POST":
        print("GOT A POST REQ")
        # If the login form is submitted
        if request.POST.get("login", ""):
            # recreating the login form via the request data
            loginform = LoginForm(request.POST)
            # if the form is valid
            if loginform.is_valid():
                print(loginform.cleaned_data)
                # checking the details from the database
                try:
                    user = authenticate(request, email=loginform.cleaned_data['email'], password=loginform.cleaned_data['password'])
                    print("User: ",user)
                    if user is not None:
                        # Message for unseen Alerts
                        try:
                            # If User has unseen alerts
                            print("Trying to check for alerts")
                            print(user.last_login)
                            print(datetime.datetime.now())
                            print(Alert.objects.filter(user_id=user, timestamp__gt=user.last_login))
                            if Alert.objects.filter(user_id=user,read=False):
                                # If user is producer
                                if user.user_type.upper()=="PRODUCER":
                                    messages.success(request, "You may have some Unseen <a class=\"alert-link\" \
                                        href=\"/producer/alerts/\">Alerts</a>", fail_silently=True)
                                # If user is consumer
                                else:
                                    messages.success(request, "You may have some Unseen <a class=\"alert-link\" \
                                                    href=\"/consumer/alerts/\">Alerts</a>", fail_silently=True)
                        except Exception as e:
                            print(e)
                            pass
                        login(request, user)
                        request.user.login_count += 1
                        request.user.last_login = datetime.datetime.now()
                        request.user.save()
                        # storing the details into the session
                        request.session['logged_in'] = True
                        request.session['user_id'] = user.pk
                        request.session['email'] = user.email
                        request.session['user_type'] = user.user_type
                    # if the logged in user is a producer
                    if request.user.user_type.upper() == "PRODUCER":
                        print("A Producer Logged In")
                        # redirect to producer home
                        return None, loginform, signupform
                    # if the logged in user is a consumer
                    else:
                        print("A Consumer Logged In")
                        # trying to restore last cart session
                        try:
                            if request.session.get('cart_id',False):
                                cart = Cart.objects.get(cart_id = request.session['cart_id'])
                                if request.session['cart_count']!=0 :
                                    request.user.last_cart = cart
                                    request.user.save()
                                else:
                                    request.session['cart_id'] = request.user.last_cart.cart_id
                            else:
                                cart = Cart.objects.get(cart_id=request.user.last_cart.cart_id)
                                request.session['cart_id'] = cart.cart_id
                                print(request.user.last_cart.cart_id)
                                if not request.user.last_cart:
                                    request.user.last_cart = cart
                                    request.user.save()
                                else:
                                    request.user.last_cart = cart.cart_id

                            return None, loginform, signupform
                        except:
                            return None, loginform, signupform

                except Exception as e:
                    loginform.add_error(None, "The username and password do not match!")
                    print(e)
        # If the signup form is submitted
        if request.POST.get("signup", ""):
            signupform = SignUpForm(request.POST)
            if signupform.is_valid():
                print(signupform.cleaned_data)
                # Creating New user
                user = signupform.save()
                request.session['logged_in'] = True
                request.session['user_id'] = user.pk
                request.session['email'] = user.email
                request.session['user_type'] = user.user_type
                login(request, user)

                message = "Hi "+str(user.first_name)+"! Please Update your Address Details to let the producers \
                           know where to deliver your orders. You can update the your profile <a href=\"/consumer/profile/\">here</a>"
                Alert.objects.create(user_id=user, message=message, type="start_message")
                print("A Consumer Logged In")
                # trying to restore last cart session
                try:
                    cart = Cart.objects.get(cart_id=user.last_cart.cart_id)
                    print(user.last_cart.cart_id)
                    if request.session.get('cart_id', False):
                        user.last_cart = cart
                        user.save()
                    else:
                        request.session['cart_id'] = cart.cart_id
                except:
                    return None, loginform, signupform
            else:
                signupform.add_error(None, "The Passwords do not match!")
            return HttpResponseRedirect('/home/'), loginform, signupform

    return None, loginform, signupform


# Function to transfer expired produce to wasted section
def remove_expired_produce():
    try:
        # Query to obtain all produce rows which have expired
        expired_produce = Produce.objects.filter(Q(date_of_expiry__lt = datetime.datetime.now())) \
                          .exclude(Q(wasted =F('weight')-F('sold')))

        for produce in expired_produce:
            machine = produce.machine_id
            user = machine.user_id
            crop = produce.crop_id
            inventory = Inventory.objects.get(user_id = user , crop_id = crop)
            produce_crop  = Crop.objects.get(crop_id = crop.crop_id)
            # Updating produce entry
            produce.wasted += produce.weight - produce.sold
            # Updating producer inventory
            inventory.wasted += produce.wasted
            # Updating overall crop availability
            produce_crop.availability -= produce.wasted
            message ="Your produce of "+produce.crop_id.english_name+" of weight "+str(produce.weight)+" logged on "+str(produce.date_of_produce.date())+" has expired on "+str(produce.date_of_expiry)
            # Transaction to save changes made to produce inventory and crop availability
            with transaction.atomic():
                # Creating Alert for informing about produce expiration
                Alert.objects.create(user_id = user,type="expiry",message = message)
                produce.save()
                inventory.save()
                produce_crop.save()
    except:
        pass


# Function to return the value for given key from a given dict in django template
@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


# Function to return the value for given key from a given list in django template
@register.filter
def get_list_item(list, key):
    return list[key]


# The view for the homepage.
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def index(request):
    # Removing expired produce
    remove_expired_produce()
    errors = []
    request.session['page'] = "/crops"

    # Handle Login and Signup.
    redirect, loginform, signupform = handle_login_signup(request)

    # If the user is a producer redirect to producer home
    if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
        return HttpResponseRedirect("/producer/home/")

    # If the user is a consumer.
    if request.user.is_authenticated and request.user.user_type.upper() == "CONSUMER":
        # A dictionary that will be passed to the template containing the maximum quantity that can be purchased
        # by consumer for each particular crop
        availability = {}
        # For storing crop_id of crops added to cart
        id = []
        # For storing crop_id of crops whose maximum purchase limit has exceeded
        exceeded_id = []
        # For storing crop_id of crops currently unavailable
        unavailable_id = []
        # If a user cart exists
        if request.session.get('cart_id', False):
            cart = Cart.objects.get(pk=request.session['cart_id'])
            cart_items = Cart_session.objects.filter(cart_id=cart)
            # Extracting details about the crops present in the cart
            for crop in cart_items:
                # Finding Minimum quantity of weight necessary for placing an order for given crop
                try:
                    min_available = Inventory.objects.filter(crop_id = crop.crop_id).aggregate(Min('minimum'))['minimum__min']
                    min_available = int(min_available)
                except:
                    min_available = 50

                # Comparing overall crop availability with minimum quantity required for placing order
                if crop.crop_id.availability >= min_available:
                    # Query to obtain all producers selling the given crop
                    producers = Inventory.objects.filter(crop_id=crop.crop_id)
                    maximum_sum = 0
                    for producer in producers:
                        if producer.weight - producer.sold - producer.wasted > producer.minimum:
                            try:
                                # Query to obtain sum of weight(quantity) of given crop ordered today by the consumer
                                order_sum = \
                                Order.objects.filter(Q(status__iexact="pending") | Q(status__iexact="delivered"),
                                                     user_id=request.user,seller = producer.user_id, crop_id=crop.crop_id,
                                                     time__date=datetime.date.today()). \
                                                     aggregate(Sum('weight'))['weight__sum']
                                order_sum = int(order_sum)
                            except:
                                order_sum = 0

                            # maximum_sum is the maximum possible quantity for the given crop that a
                            # particular consumer can purchase
                            maximum_sum += int(
                                min(producer.maximum - order_sum, (producer.weight - producer.sold - producer.wasted)))

                    availability[crop.crop_id.crop_id] = maximum_sum
                    # if crop is available
                    if availability[crop.crop_id.crop_id] >= 0:
                        # if availability is greater than min_available
                        if availability[crop.crop_id.crop_id] >= min_available:
                            id.append(crop.crop_id.crop_id)
                        else:
                            exceeded_id.append(crop.crop_id.crop_id)
                            # Create error message
                            message = "Sorry you have reached your daily limit for purchasing " + crop.crop_id.english_name
                            errors.append(message)
                            # Remove crop from cart
                            crop.delete()
                    else:
                        unavailable_id.append(crop.crop_id.crop_id)
                        # Create error message
                        message = "Sorry " + crop.crop_id.english_name + " is no longer available!"
                        errors.append(message)
                        # Remove crop from cart
                        crop.delete()
                else:
                    unavailable_id.append(crop.crop_id.crop_id)
                    message = "Sorry " + crop.crop_id.english_name + " is no longer available!"
                    errors.append(message)
                    # Remove crop from cart
                    crop.delete()

        # Query to obtain crops currently added in cart after validation
        added_crops = Crop.objects.filter(crop_id__in=id).order_by('-availability')
        # Updating number of items in cart
        request.session['cart_count'] = added_crops.count()

        id = id + exceeded_id + unavailable_id
        # Query to obtain crops available for purchase
        crops = Crop.objects.exclude(crop_id__in=id).order_by('-availability')

        for crop in crops:
            # Finding Minimum quantity of weight necessary for placing an order for given crop
            try:
                min_available = Inventory.objects.filter(crop_id=crop).aggregate(Min('minimum'))['minimum__min']
                min_available = int(min_available)
            except Exception as e:
                min_available = 50
            # Comparing overall crop availability with minimum quantity required for placing order
            if crop.availability >= min_available:
                # Query to obtain all producers selling the given crop
                producers = Inventory.objects.filter(crop_id=crop)
                maximum_sum = 0
                for producer in producers:
                    if producer.weight - producer.sold - producer.wasted > producer.minimum:
                        try:
                            # Query to obtain sum of weight(quantity) of given crop ordered today by the consumer
                            order_sum = Order.objects.filter(Q(status__iexact="pending") | Q(status__iexact="delivered"),
                                                             user_id=request.user,seller = producer.user_id, crop_id=crop,
                                                             time__date=datetime.date.today()). \
                                                             aggregate(Sum('weight'))['weight__sum']
                            order_sum = int(order_sum)
                        except:
                            order_sum = 0
                        # maximum_sum is the maximum possible quantity for the given crop that a
                        # particular consumer can purchase
                        maximum_sum += int(min((producer.maximum - order_sum), (producer.weight - producer.sold - producer.wasted)))

                availability[crop.crop_id] = maximum_sum
                # if crop is available
                if availability[crop.crop_id] >= 0:
                    # if availability is less than minimum quantity
                    if availability[crop.crop_id] < min_available:
                        exceeded_id.append(crop.crop_id)
                else:
                    unavailable_id.append(crop.crop_id)
            else:
                unavailable_id.append(crop.crop_id)

        # Query to obtain unavailable crops
        unavailable_crops = Crop.objects.filter(crop_id__in=unavailable_id).order_by('-availability')
        # Query to obtain crops whose purchase limit has exceeded
        exceeded_crops = Crop.objects.filter(crop_id__in=exceeded_id).order_by('-availability')
        id = id + exceeded_id + unavailable_id
        crops = Crop.objects.exclude(crop_id__in=id).order_by('-availability')

        context = {'page': 'home','crops': crops, 'added_crops': added_crops ,'unavailable_crops':unavailable_crops, 'exceeded_crops':exceeded_crops, 'errors': errors,
                   'availability': availability}

        return render(request, 'login/shop.html', context)
    # The user is not logged in.
    else:
        availability = {}
        # If user cart exists
        if request.session.get('cart_id', False):
            cart = Cart.objects.get(cart_id=request.session['cart_id'])
            cart_items = Cart_session.objects.filter(cart_id=cart)

            id = []
            for crop in cart_items:
                # Finding Minimum quantity of weight necessary for placing an order for given crop
                try:
                    min_available = Inventory.objects.filter(crop_id = crop.crop_id).aggregate(Min('minimum'))['minimum__min']
                    min_available = int(min_available)
                except:
                    min_available = 50
                if (crop.crop_id.availability >= min_available):
                    id.append(crop.crop_id.crop_id)
                else:
                    message = "Sorry " + crop.crop_id.english_name + " is no longer available!"
                    errors.append(message)
                    print(errors)
                    Cart_session.objects.get(cart_id=crop.cart_id).delete()
            added_crops = Crop.objects.filter(crop_id__in=id).order_by('-availability')
            request.session['cart_count'] = added_crops.count()
            crops = Crop.objects.exclude(crop_id__in=id).order_by('-availability')

        else:
            crops = Crop.objects.all().order_by('-availability')
            added_crops = []

        for crop in crops:
            try:
                min_available = Inventory.objects.filter(crop_id=crop).aggregate(Min('minimum'))['minimum__min']
                min_available = int(min_available)
            except Exception as e:
                min_available = 50
            if crop.availability >= min_available:
                availability[crop.crop_id] = 1
            else:
                availability[crop.crop_id] = 0

        context = {'loginform': loginform, 'signupform': signupform, 'page': 'crops', 'crops': crops,
                   'added_crops': added_crops, 'errors': errors , 'availability':availability}
        return render(request, 'shop.html', context)

# The view for consumer home. The page has been removed and redirected to 'crops/' i.e. the store
def home(request):
    # Removing expired produce
    remove_expired_produce()
    # Checking if user is authenticated and user_type is PRODUCER
    if request.user.is_authenticated and request.user.user_type.upper() != "PRODUCER":
        if request.session.get('cart_id', False):
            if request.session.get('page', False):
                return HttpResponseRedirect(request.session['page'])
            else:
                return HttpResponseRedirect('/crops')
        else:
            return HttpResponseRedirect('/crops')
    return HttpResponseRedirect('/')

# The view to logout a user. It flushes the user session.
def log_out(request):
    # Checking if user is authenticated
    if request.user.is_authenticated:
        # if cart exists
        if request.session.get('cart_id', None):
            try:
                # Save user cart
                request.user.last_cart = Cart.objects.get(cart_id=request.session['cart_id'])
                request.user.save()

            except:
                pass
        try:
            all_alerts = Alert.objects.filter(user_id=request.user,read = False)
            for alert in all_alerts:
                alert.read = True
                alert.save()
        except:
            pass
        logout(request)
        request.session.flush()
        return HttpResponseRedirect('/')
    # Flushing session on successfull logout
    request.session.flush()
    return HttpResponseRedirect('/')

# The view for producer home.
def producer_home(request):
    # Removing expired produce
    remove_expired_produce()
    if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
        # Fetch all information about the logged produce
        try:
            # Query to obtain all machines owned by producer
            machines = Machine.objects.filter(user_id=request.user)
            # Query to obtain the produce
            produce = list(Produce.objects.filter(machine_id__in=machines).order_by('-timestamp'))
        except:
            pass
        return render(request, 'producer.html', {'page': "home", 'produce': produce})
    return HttpResponseRedirect('/')


# The view for producer inventory
def producer_inventory(request):
    # Removing expired produce
    remove_expired_produce()
    if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
        # Fetch all information about the producer inventory
        inventory = []
        try:
            # Query to obtain producer and his inventory
            inventory = Inventory.objects.filter(user_id=request.user)
        except Exception as e:
            print(e)
            pass
        return render(request, 'producer_inventory.html', {'page': "inventory", 'inventory': inventory})
    return HttpResponseRedirect('/')


# The view for the about page
def about(request):
    # Updating current page
    request.session['page'] = '/about'
    redirect, loginform, signupform = handle_login_signup(request)
    # Checking if user is logged in and producer
    if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
        return HttpResponseRedirect("/")
    # Checking if user is logged in and consumer
    if request.user.is_authenticated and request.user.user_type.upper() == "CONSUMER":
        context = {'page': 'about'}
        return render(request, 'login/about.html', context)
    else:
        context = {'loginform': loginform, 'signupform': signupform, 'page': 'about'}
        return render(request, 'about.html', context)


# The view for the crops page. Has been moved to the homepage('/')
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def crops(request):
    return HttpResponseRedirect("/")


# The view to add item to cart and redirect back.
def add_to_cart(request, crop_id):
    # Removing expired produce
    remove_expired_produce()
    try:
        # Query to obtain crop object to be added to cart
        input_crop = Crop.objects.get(crop_id=crop_id)
        # Creating cart_session object
        cart_session = Cart_session()
        try:
            # Obtaining minimum quantity required for purchase of given crop
            min_available = Inventory.objects.filter(crop_id = input_crop).aggregate(Min('minimum'))['minimum__min']
            min_available = int(min_available)
        except:
            min_available = 50
        # Comparing crop availability and min_available
        if input_crop.availability > min_available:
            # if cart exists
            if request.session.get('cart_id', False):
                try:
                    # Query to obtain cart object
                    cart = Cart.objects.get(cart_id=request.session['cart_id'])
                    Cart_session.objects.get(cart_id=cart, crop_id=input_crop)
                    return HttpResponseRedirect('/crops')
                except:
                    cart = Cart.objects.get(cart_id=request.session['cart_id'])
                    cart_session.cart_id = cart
            else:
                # Create new cart if cart does not exist
                cart = Cart.objects.create()
                cart_session.cart_id = cart
                # Adding cart_id in session
                request.session['cart_id'] = cart.cart_id

            cart_session.crop_id = input_crop
            cart_session.save()
        return HttpResponseRedirect('/crops')
    except:
        return HttpResponseRedirect('/crops')

# The view to remove item from cart and redirect back
def remove_from_cart(request, crop_id):
    try:
        # Query to obtain crop to be removed from cart
        input_crop = Crop.objects.get(crop_id=crop_id)
        # if cart exists
        if request.session.get('cart_id', False):
            cart = Cart.objects.get(cart_id=request.session['cart_id'])
            Cart_session.objects.get(cart_id=cart, crop_id=input_crop).delete()
        # if current page exists in session
        if request.session.get('page', False):
            return HttpResponseRedirect(request.session['page'])
        else:
            return HttpResponseRedirect('/')
    except:
        if request.session.get('page', False):
            return HttpResponseRedirect(request.session['page'])
        else:
            return HttpResponseRedirect('/')


# The view for the cart page. Shows information anout the items present in the cart.
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def view_cart(request):
    # Removing expired produce
    remove_expired_produce()
    errors = []
    request.session['page'] = "/cart"
    redirect, loginform, signupform = handle_login_signup(request)

    # If the user is a producer redirect to producer home
    if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
        return HttpResponseRedirect("/producer/home/")

    # If the user is a consumer
    if request.user.is_authenticated and request.user.user_type.upper() == "CONSUMER":
        try:
            # dictionary to store crop availability
            availability = {}
            if request.session.get('cart_id', False):
                cart = Cart.objects.get(cart_id=request.session['cart_id'])
                # Query to obtain items currently added in cart

                cart_items = Cart_session.objects.filter(cart_id=cart)
                id = []

                for crop in cart_items:
                    try:
                        # Query to obtain minimum quantity necessary for purchase of crop
                        min_available = Inventory.objects.filter(crop_id=crop.crop_id).aggregate(Min('minimum'))[
                            'minimum__min']
                        min_available = int(min_available)
                    except:
                        min_available = 50
                    # Comparing crop availability with min_available
                    if (crop.crop_id.availability >= min_available):
                        # Query to obtain all producers selling the given crop
                        producers = Inventory.objects.filter(crop_id=crop.crop_id)
                        maximum_sum = 0
                        for producer in producers:
                            if producer.weight - producer.sold - producer.wasted >= producer.minimum:
                                try:
                                    # Query to obtain sum of weight(quantity) of given crop ordered today by the consumer
                                    order_sum = \
                                        Order.objects.filter(
                                            Q(status__iexact="pending") | Q(status__iexact="delivered"),
                                            user_id=request.user, seller=producer.user_id, crop_id=crop.crop_id,
                                            time__date=datetime.date.today()). \
                                            aggregate(Sum('weight'))['weight__sum']
                                    order_sum = int(order_sum)
                                except:
                                    order_sum = 0
                                print(order_sum)
                                maximum_sum += int(
                                    min((producer.maximum - order_sum),
                                        (producer.weight - producer.sold - producer.wasted)))

                        availability[crop.crop_id.crop_id] = maximum_sum

                        if availability[crop.crop_id.crop_id] >= 0:
                            # Comparing crop availability and min_available
                            if availability[crop.crop_id.crop_id] >= min_available:
                                id.append(crop.crop_id.crop_id)
                            else:
                                # Removing crop from cart if exceeded daily limit
                                message = "Sorry you have reached your daily limit for purchasing " + crop.crop_id.english_name
                                errors.append(message)
                                print(errors)
                                crop.delete()
                        else:
                            # Removing crop from cart if not available
                            message = "Sorry " + crop.crop_id.english_name + " is no longer available!"
                            errors.append(message)
                            print(errors)
                            crop.delete()
                    else:
                        # Removing crop from cart if not available
                        message = "Sorry " + crop.crop_id.english_name + " is no longer available!"
                        errors.append(message)
                        print(errors)
                        crop.delete()
                print("arrgh 5")
                added_crops = Crop.objects.filter(crop_id__in=id).order_by('-availability')
                request.session['cart_count'] = added_crops.count()
                if request.session['cart_count'] == 0:
                    return HttpResponseRedirect('/crops')

                cart_items = Cart_session.objects.filter(cart_id=cart)
                context = {'page': 'cart', 'cart_session': cart_items, 'availability': availability, 'errors': errors}
                return render(request, 'login/cart.html', context)

            else:
                return HttpResponseRedirect('/')
        except Exception as e:
            print(e)
            return HttpResponseRedirect('/')
    # if user is not logged in
    else:
        try:
            redirect, loginform, signupform = handle_login_signup(request)

            cart = Cart.objects.get(cart_id=request.session['cart_id'])
            cart_session = Cart_session.objects.filter(cart_id=cart)
            errors = []

            id = []
            for crop in cart_session:
                try:
                    min_available = Inventory.objects.filter(crop_id = crop.crop_id).aggregate(Min('minimum'))['minimum__min']
                    min_available = int(min_available)
                except:
                    min_available = 50
                if crop.crop_id.availability >= min_available:
                    id.append(crop.crop_id.crop_id)
                else:
                    message = "Sorry " + crop.crop_id.english_name + " is no longer available!"
                    errors.append(message)
                    print(errors)
                    Cart_session.objects.get(cart_id=crop.cart_id).delete()
            added_crops = Crop.objects.filter(crop_id__in=id, availability__gt=0).order_by('-availability')
            request.session['cart_count'] = added_crops.count()
            if request.session['cart_count'] == 0:
                return HttpResponseRedirect('/crops')

            context = {'loginform': loginform, 'signupform': signupform, 'page': 'cart', 'cart_session': cart_session,
                       'errors': errors}
            return render(request, 'cart.html', context)
        except:
            return HttpResponseRedirect('/crops')


# The view for the checkout page.
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def checkout(request):
    # Removing expired produce
    remove_expired_produce()
    # if user is logged in and consumer
    if request.user.is_authenticated and request.user.user_type.upper() == "CONSUMER" and request.user.address_line1:
        outerlist = {}
        errors = {}
        error_flag = 0
        form_values = {}
        try:
            # if cart exists
            if request.session.get('cart_id', False):
                # if request method is POST
                if request.method == "POST":
                    try:
                        # Creating a transaction
                        with transaction.atomic():
                            # Obtaining items currently added to cart
                            cart = Cart.objects.get(cart_id=request.session['cart_id'])
                            cart_session = Cart_session.objects.filter(cart_id=cart)
                            valid_producers = []
                            # Validating requested quantity with available quantity for each cart item
                            for item in cart_session:
                                producers = Inventory.objects.filter(crop_id=item.crop_id, weight__gte=F('minimum'))
                                item_errors = []
                                for producer in producers:
                                    requested_quantity = request.POST.get(
                                        producer.user_id.first_name + str(producer.crop_id.crop_id))
                                    form_values[producer.user_id.first_name + str(producer.crop_id.crop_id)] = int(
                                        requested_quantity)
                                    requested_quantity = float(requested_quantity)
                                    print(requested_quantity)
                                    if requested_quantity != 0:
                                        # Comparing available and requested quantity
                                        if (producer.weight - producer.sold - producer.wasted) < requested_quantity and (
                                                    producer.weight - producer.sold - producer.wasted) >= producer.minimum:
                                            # Creating error message
                                            message = "Sorry " + producer.crop_id.english_name + \
                                                " is  unavailable as requested quantity of " \
                                                + str(requested_quantity) + "gm is greater than available quantity of "\
                                                + str(producer.weight - producer.sold - producer.wasted) + "gm !"
                                            form_values[producer.user_id.first_name + str(producer.crop_id.crop_id)] = 0
                                            error_flag = 1
                                            item_errors.append(message)
                                        elif (producer.weight - producer.sold - producer.wasted) < producer.minimum:
                                            message = "Sorry " + producer.user_id.first_name + " does not have enough "\
                                                      + producer.crop_id.english_name + "!"
                                            form_values[producer.user_id.first_name + str(producer.crop_id.crop_id)] = 0
                                            error_flag = 1
                                            item_errors.append(message)
                                        else:
                                            # if no errors occur adding producer to valid_producers
                                            valid_producers.append(producer)
                                    errors[item.crop_id.crop_id] = item_errors
                            # if no errors occur
                            if error_flag == 0:
                                for producer in valid_producers:
                                    requested_quantity = request.POST.get(
                                        producer.user_id.first_name + str(producer.crop_id.crop_id))
                                    requested_quantity = float(requested_quantity)
                                    crop = Crop.objects.get(crop_id=producer.crop_id.crop_id)

                                    if requested_quantity != 0:
                                        # Placing order for each particular valid order entry
                                        try:
                                            order = Order(user_id=request.user, cart_id=cart, crop_id=producer.crop_id,
                                                          seller=producer.user_id, weight=requested_quantity)

                                            crop = Crop.objects.get(crop_id=producer.crop_id.crop_id)
                                            inventory = Inventory.objects.select_for_update().get(
                                                user_id=producer.user_id, crop_id=crop)
                                            final_inventory = inventory.weight - inventory.sold - inventory.wasted
                                            # Verifying if order can be placed by comparing requested quantity and
                                            # available quantity
                                            if requested_quantity <= final_inventory:
                                                inventory.sold = F('sold') + requested_quantity
                                                crop.availability = F('availability') - requested_quantity
                                                # Creating transaction for secure placement of order
                                                with transaction.atomic():
                                                    inventory.save()
                                                    order.save()
                                                    crop.save()
                                            else:
                                                return HttpResponseRedirect('/checkout')
                                        except Exception as e:
                                            print(e)
                                            return HttpResponseRedirect('/checkout')

                                return HttpResponseRedirect('/order')
                    except Exception as e:
                        print(e)
                        return HttpResponseRedirect('/checkout')

                # Obtaining current cart items
                cart = Cart.objects.get(cart_id=request.session['cart_id'])
                cart_session = Cart_session.objects.filter(cart_id=cart)

                for item in cart_session:
                    # Query to obtain producers selling the given crop
                    producers = Inventory.objects.filter(crop_id=item.crop_id, weight__gte=F('minimum'))
                    item_list = []
                    for producer in producers:
                        machines = Machine.objects.filter(user_id=producer.user_id)
                        row = \
                            Produce.objects.filter(machine_id__in=machines, crop_id=producer.crop_id).order_by(
                                '-date_of_produce')[
                                0]
                        innerlist = []
                        innerlist.append(producer.user_id)
                        innerlist.append(producer.crop_id)
                        innerlist.append(producer.weight - producer.sold - producer.wasted)
                        innerlist.append(producer.minimum)
                        innerlist.append(producer.maximum)
                        innerlist.append(row.image)

                        quantity = []
                        i = int(producer.minimum)
                        order_sum = 0
                        try:
                            # Query to obtain sum of weight(quantity) of given crop ordered today by the consumer
                            order_sum = \
                            Order.objects.filter(Q(status__iexact="pending") | Q(status__iexact="delivered"),
                                                 user_id=request.user,seller = producer.user_id, crop_id=item.crop_id, time__date=datetime.date.today()). \
                                                 aggregate(Sum('weight'))['weight__sum']
                            order_sum = int(order_sum)
                            print(order_sum)
                        except:
                            order_sum = 0
                        finally:
                            max = min(int(producer.maximum - order_sum), int(producer.weight - producer.sold - producer.wasted))
                            print(max)
                            # Quantity is a list containing possible quantities which can be purchased for each producer
                            # for each crop
                            if i <= max:
                                while i <= max:
                                    quantity.append(i)
                                    i = i + int(producer.minimum)
                                if quantity[len(quantity) - 1] != max:
                                    quantity.append(max)
                            else:
                                quantity.append("Unavailable")
                            print(quantity)
                            innerlist.append(quantity)
                            innerlist.append(producer.user_id.first_name + str(producer.crop_id.crop_id))
                            innerlist.append(max)
                            item_list.append(innerlist)
                            print(quantity)
                    outerlist[item.crop_id.crop_id] = item_list
                context = {'page': 'checkout', 'cart_session': cart_session, 'outerlist': outerlist, 'errors': errors,
                           'form_values': form_values}
                return render(request, 'login/checkout.html', context)
            else:
                return HttpResponseRedirect('/crops')
        except:
            return HttpResponseRedirect('/')
    else:
        return HttpResponseRedirect('/')


# The view for the order summary page.
def order_summary(request):
    try:
        if request.user.is_authenticated and request.user.user_type.upper() == "CONSUMER":
            cart = Cart.objects.get(cart_id=request.session['cart_id'])
            request.user.last_cart = None
            request.user.save()
            # Query to obtain order details
            orders = Order.objects.filter(user_id=request.user, cart_id=cart)

            for order in orders:
                consumer_message =\
                "Your order for "+order.crop_id.english_name +" of quantity "+str(order.weight)+" g from producer "\
                +order.seller.first_name+ " was successfully placed on "+str(order.time.date())+ \
                ". The produce should be delivered to you by the next working day."

                producer_message = \
                    "You have received an order for " + order.crop_id.english_name + " of quantity " +\
                    str(order.weight)+ " g from " + order.user_id.first_name+" on "+str(order.time.date())

                Alert.objects.create(user_id=order.user_id,type = 'ordered',message = consumer_message )
                Alert.objects.create(user_id=order.seller, type='ordered', message= producer_message)
                try:
                    # Query to obtain machines owned by producer
                    machines = Machine.objects.filter(user_id=order.seller.pk)
                    # Query to obtain produce
                    produce = Produce.objects.filter(machine_id__in=machines,
                                                     crop_id=order.crop_id,
                                                     date_of_expiry__gt=datetime.datetime.now(),
                                                     weight__gt=F('sold')).order_by('date_of_expiry')
                    # Updating produce entries
                    quantity_left = order.weight
                    for entry in produce:
                        if quantity_left > 0:
                            if entry.weight - entry.sold - entry.wasted >= quantity_left:
                                entry.sold = entry.sold + quantity_left
                                with transaction.atomic():
                                    entry.save()
                                break
                            else:
                                quantity_left = quantity_left - (entry.weight - entry.sold -entry.wasted)
                                entry.sold = entry.weight - entry.wasted
                                with transaction.atomic():
                                    entry.save()

                except Exception as e:
                    print(e)
                    return HttpResponseRedirect('/crops')

            if orders:
                # Removing cart session
                del request.session['cart_id']
                del request.session['cart_count']

                return render(request, 'login/order.html', {'orders': orders})
            else:
                return HttpResponseRedirect('/crops')
        else:
            return HttpResponseRedirect('/')
    except Exception as e:
        print(e)
        return HttpResponseRedirect('/')


# The view for the producer orders page. Shows all the orders.
def producer_orders(request):
    try:
        # If user is authenticated and producer
        if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
            request.session['page'] = "/producer/orders"
            # Query to obtain all orders received by producer
            orders = Order.objects.filter(seller=request.user).order_by('-cart_id')
            # if orders exist
            if orders:
                # all_orders contains orders grouped by crops
                all_orders = {}
                for order in orders:
                    if all_orders.get(order.crop_id.english_name, False):
                        print("")
                    else:
                        all_orders[order.crop_id.english_name] = []
                    item_order = {}
                    item_order['cart_id'] = order.cart_id
                    item_order['crop_id'] = order.crop_id
                    item_order['user_id'] = order.user_id
                    item_order['weight'] = order.weight
                    item_order['time'] = order.time
                    item_order['status'] = order.status.upper()
                    all_orders[order.crop_id.english_name].append(item_order)

                context = {'page': "orders", 'all_orders': all_orders}
                return render(request, 'producerOrder.html', context)
            else:
                context = {'page': "orders"}
                return render(request, 'producerOrder.html', context)
        else:
            return HttpResponseRedirect('/')
    except:
        return HttpResponseRedirect('/')


# The view for the producer pending orders.
def producer_pending_orders(request):
    try:
        # If user is authenticated and producer
        if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
            request.session['page'] = "/producer/pendingorders"
            # Query to obtain pending orders received by producer
            orders = Order.objects.filter(seller=request.user, status__iexact='pending').order_by('-cart_id')
            # if orders exist
            if orders:
                # all_orders contains pending orders grouped by crops
                all_orders = {}

                for order in orders:
                    if all_orders.get(order.crop_id.english_name, False):
                        print("")
                    else:
                        all_orders[order.crop_id.english_name] = []
                    item_order = {}
                    item_order['cart_id'] = order.cart_id
                    item_order['crop_id'] = order.crop_id
                    item_order['user_id'] = order.user_id
                    item_order['weight'] = order.weight
                    item_order['time'] = order.time
                    item_order['status'] = order.status.upper()
                    all_orders[order.crop_id.english_name].append(item_order)

                context = {'page': "orders", 'all_orders': all_orders}
                return render(request, 'producerPendingOrder.html', context)
            else:
                context = {'page': "orders"}
                return render(request, 'producerPendingOrder.html', context)
        else:
            return HttpResponseRedirect('/')
    except:
        return HttpResponseRedirect('/')


# The view for the delivery page.
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def producer_delivery(request):
    try:
        # If user is authenticated and producer
        if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
            request.session['page'] = "/producer/delivery"
            # Query to obtain orders to be delivered
            orders = Order.objects.filter(seller=request.user, status="pending").order_by('-cart_id')
            # if orders exist
            if orders:
                prev_order = orders[0].cart_id.cart_id
                # all_orders consists of orders to be delivered grouped by each individual order
                all_orders = []
                individual_order = []
                for order in orders:
                    if order.cart_id.cart_id != prev_order:
                        all_orders.append(individual_order)
                        individual_order = []
                        prev_order = order.cart_id.cart_id

                    item_order = {}
                    item_order['cart_id'] = order.cart_id
                    item_order['crop_id'] = order.crop_id
                    item_order['buyer'] = order.user_id
                    item_order['weight'] = order.weight
                    item_order['time'] = order.time
                    item_order['status'] = order.status.upper()
                    individual_order.append(item_order)
                all_orders.append(individual_order)

                paginator = Paginator(all_orders, 5)  # Show 5 orders per page

                page = request.GET.get('page')
                try:
                    orders = paginator.page(page)
                except PageNotAnInteger:
                    # If page is not an integer, deliver first page.
                    orders = paginator.page(1)
                except EmptyPage:
                    # If page is out of range (e.g. 9999), deliver last page of results.
                    orders = paginator.page(paginator.num_pages)

                pagelist = []
                for i in range(1, orders.paginator.num_pages + 1):
                    pagelist.append(i)
                print(paginator.num_pages)
                context = {'page': "delivery", 'all_orders': orders, 'pagelist': pagelist}
                return render(request, 'producerDelivery.html', context)
            else:
                context = {'page': "delivery"}
                return render(request, 'producerDelivery.html', context)
        else:
            return HttpResponseRedirect('/')
    except:
        return HttpResponseRedirect('/')


# The view for the delivered orders of producer
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def producer_delivered(request):
    try:
        # If user is authenticated and producer
        if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
            # Query to obtain orders already delivered
            orders = Order.objects.filter(seller=request.user, status__iexact="delivered").order_by('-delivery_date')
            # if orders exist
            if orders:
                prev_order = orders[0].cart_id.cart_id
                # all_orders consists of delivered orders grouped by consumers
                all_orders = []
                individual_order = []
                for order in orders:
                    if order.cart_id.cart_id != prev_order:
                        all_orders.append(individual_order)
                        individual_order = []
                        prev_order = order.cart_id.cart_id

                    item_order = {}
                    item_order['cart_id'] = order.cart_id
                    item_order['crop_id'] = order.crop_id
                    item_order['buyer'] = order.user_id
                    item_order['weight'] = order.weight
                    item_order['time'] = order.time
                    item_order['delivery_date'] = order.delivery_date
                    item_order['status'] = order.status.upper()
                    individual_order.append(item_order)
                all_orders.append(individual_order)

                paginator = Paginator(all_orders, 5)  # Show 5 orders per page

                page = request.GET.get('page')
                try:
                    orders = paginator.page(page)
                except PageNotAnInteger:
                    # If page is not an integer, deliver first page.
                    orders = paginator.page(1)
                except EmptyPage:
                    # If page is out of range (e.g. 9999), deliver last page of results.
                    orders = paginator.page(paginator.num_pages)

                pagelist = []
                for i in range(1, orders.paginator.num_pages + 1):
                    pagelist.append(i)
                print(paginator.num_pages)
                context = {'page': "orders", 'all_orders': orders, 'pagelist': pagelist}
                return render(request, 'producerDelivered.html', context)
            else:
                context = {'page': "orders"}
                return render(request, 'producerDelivered.html', context)
        else:
            return HttpResponseRedirect('/')
    except:
        return HttpResponseRedirect('/')


# The view for the consumer orders page.
def consumer_orders(request):
    try:
        # if user is authenticated and consumer
        if request.user.is_authenticated and request.user.user_type.upper() == "CONSUMER":
            request.session['page'] = "/consumer/orders"
            # Query to obtain all orders placed by consumer
            orders = Order.objects.filter(user_id=request.user).order_by('-cart_id')
            if orders:
                prev_order = orders[0].cart_id.cart_id
                # all_orders consists of orders placed by consumer grouped by individual orders
                all_orders = []
                individual_order = []
                for order in orders:
                    if order.cart_id.cart_id != prev_order:
                        all_orders.append(individual_order)
                        individual_order = []
                        prev_order = order.cart_id.cart_id

                    item_order = {}
                    item_order['cart_id'] = order.cart_id
                    item_order['crop_id'] = order.crop_id
                    item_order['seller'] = order.seller
                    item_order['weight'] = order.weight
                    item_order['time'] = order.time
                    item_order['status'] = order.status.upper()
                    individual_order.append(item_order)
                all_orders.append(individual_order)

                paginator = Paginator(all_orders, 5)  # Show 5 orders per page

                page = request.GET.get('page')
                try:
                    orders = paginator.page(page)
                except PageNotAnInteger:
                    # If page is not an integer, deliver first page.
                    orders = paginator.page(1)
                except EmptyPage:
                    # If page is out of range (e.g. 9999), deliver last page of results.
                    orders = paginator.page(paginator.num_pages)

                pagelist = []
                for i in range(1, orders.paginator.num_pages + 1):
                    pagelist.append(i)
                print(paginator.num_pages)
                context = {'page': "orders", 'all_orders': orders, 'pagelist': pagelist}
                return render(request, 'consumerOrder.html', context)
            else:
                context = {'page': "orders"}
                return render(request, 'consumerOrder.html', context)
        else:
            return HttpResponseRedirect('/')
    except Exception as e:
        print(e)
        return HttpResponseRedirect('/')


# This view renders page showing delivered orders of consumer
def consumer_delivered(request):
    try:
        # if user is authenticated and consumer
        if request.user.is_authenticated and request.user.user_type.upper() == "CONSUMER":
            # Query to obtain all orders delivered to consumer
            orders = Order.objects.filter(user_id=request.user, status__iexact="delivered").order_by('-delivery_date')

            if orders:
                prev_order = orders[0].cart_id.cart_id
                # all_orders consists of orders delivered to consumer grouped by individual orders
                all_orders = []
                individual_order = []
                # form consists reviews given by consumer for each order
                form = {}
                form_values ={}
                for order in orders:
                    if order.cart_id.cart_id != prev_order:
                        all_orders.append(individual_order)
                        individual_order = []
                        prev_order = order.cart_id.cart_id

                    item_order = {}
                    item_order['cart_id'] = order.cart_id
                    item_order['crop_id'] = order.crop_id
                    item_order['seller'] = order.seller
                    item_order['buyer'] = order.user_id
                    item_order['weight'] = order.weight
                    item_order['time'] = order.time
                    item_order['delivery_date'] = order.delivery_date
                    item_order['status'] = order.status.upper()
                    try:
                        rating = float(Review.objects.filter(user_id = order.seller).aggregate(Avg('rating'))['rating__avg'])
                    except:
                        rating = 0
                    item_order['rating'] = "{:4.2f}".format(rating)
                    individual_order.append(item_order)
                    try:
                        # if consumer has already reviewed the order
                        review = Review.objects.get(user_id=order.seller, customer=order.user_id, cart_id=order.cart_id)
                        form_values['rating'] = review.rating
                        form_values['review'] = review.review
                        form[order.cart_id.cart_id] = form_values
                        form_values ={}
                    except Exception as e:
                        # if consumer has not yet reviewed order
                        form_values['rating'] = 0
                        form_values['review'] = ""
                        form[order.cart_id.cart_id] = form_values
                        form_values = {}
                all_orders.append(individual_order)
                print(form)


                paginator = Paginator(all_orders, 5)  # Show 5 orders per page

                page = request.GET.get('page')
                try:
                    orders = paginator.page(page)
                except PageNotAnInteger:
                    # If page is not an integer, deliver first page.
                    orders = paginator.page(1)
                except EmptyPage:
                    # If page is out of range (e.g. 9999), deliver last page of results.
                    orders = paginator.page(paginator.num_pages)

                pagelist = []
                for i in range(1, orders.paginator.num_pages + 1):
                    pagelist.append(i)
                print(paginator.num_pages)

                context = {'page': "deliveredorders", 'all_orders': orders, 'pagelist': pagelist ,'form':form}
                return render(request, 'consumerDelivered.html', context)
            else:
                context = {'page': "deliveredorders"}
                return render(request, 'consumerDelivered.html', context)
        else:
            return HttpResponseRedirect('/')
    except Exception as e:
        print(e)
        return HttpResponseRedirect('/')


# This view renders the page displaying reviews received by producer
def producer_reviews(request):
    try:
        # if user is authenticated and producer
        if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
            # Query to obtain reviews for producer
            all_reviews = Review.objects.filter(user_id=request.user)
            # Query to obtain average rating
            rating = float(Review.objects.filter(user_id=request.user).aggregate(Avg('rating'))['rating__avg'])
            rating = "{:4.2f}".format(rating)

            paginator = Paginator(all_reviews, 5)  # Show 5 orders per page

            page = request.GET.get('page')
            try:
                reviews = paginator.page(page)
            except PageNotAnInteger:
                # If page is not an integer, deliver first page.
                reviews = paginator.page(1)
            except EmptyPage:
                # If page is out of range (e.g. 9999), deliver last page of results.
                reviews = paginator.page(paginator.num_pages)

            pagelist = []
            for i in range(1, reviews.paginator.num_pages + 1):
                pagelist.append(i)
            print(paginator.num_pages)

            context = {'page': "reviews", 'all_reviews': reviews,'rating':rating, 'pagelist': pagelist}
            return render(request, 'producerReviews.html', context)
        else:
            return HttpResponseRedirect('/')
    except:
        rating = 0
        context = {'page': "reviews", 'rating': rating}
        return render(request, 'producerReviews.html', context)


# This view is used to store review written by consumer into database
def process_review(request,cart_id,seller):
    try:
        if request.method == "POST":
            # Queries to obtain cart,consumer,seller for given order
            cart = Cart.objects.get(cart_id = cart_id)
            user = request.user
            producer = User.objects.get(pk = seller)

            try:
                # if review already exists
                review = Review.objects.get(user_id = producer , customer = user, cart_id = cart)
                review.rating = request.POST.get('rating')
                review.customer = request.user
                review.user_id = producer
                review.cart_id = cart
                review.review = request.POST.get('review')
                review.save()
                messages.success(request, "Your Review was Successfully Updated!", fail_silently=True)
                return HttpResponseRedirect('/consumer/deliveredorders')
            except:
                # if not yet reviewed
                Review.objects.create(rating = request.POST.get('rating'),customer = request.user,user_id = producer,cart_id = cart,review = request.POST.get('review'))
                messages.success(request, "Your Review was Successfully Submitted!", fail_silently=True)
                return HttpResponseRedirect('/consumer/deliveredorders')
        else:
            return HttpResponseRedirect('/')
    except:
        return HttpResponseRedirect('/')


# The view for consumer to cancel a particular order
def consumer_order_cancel(request, cart_id, seller, crop_id):
    try:
        # if user is authenticated and consumer
        if request.user.is_authenticated and request.user.user_type.upper() == "CONSUMER":
            # Queries to obtain seller, cart and crop
            seller = User.objects.get(pk=seller)
            cart = Cart.objects.get(cart_id=cart_id)
            crop = Crop.objects.get(crop_id=crop_id)
            # Query to obtain order to be cancelled
            order = Order.objects.get(user_id=request.user, cart_id=cart, crop_id=crop, seller=seller)
            order.status = "cancelled"
            producer_message = order.user_id.first_name + " has cancelled his order for " + str(order.weight) + " grams of " \
                               + order.crop_id.english_name + " placed on " + str(order.time.date())
            # Updating crop availability
            crop.availability = crop.availability + order.weight
            inventory = Inventory.objects.get(user_id=seller, crop_id=crop)
            # Updating inventory
            inventory.sold = inventory.sold - order.weight
            # Creating alert for cancellation of order
            Alert.objects.create(user_id=seller,type = "cancelled", message=producer_message)
            # Creating transaction to save changes
            with transaction.atomic():
                order.save()
                inventory.save()
                crop.save()
                # Query to obtain machines owned by seller
                machines = Machine.objects.filter(user_id=seller)
                # Query to obtain produce
                produce = Produce.objects.filter(machine_id__in=machines,
                                                 crop_id=crop,
                                                 date_of_expiry__gt=datetime.datetime.now(),
                                                 ).exclude(sold=0).order_by('-date_of_expiry')

                quantity_left = order.weight
                # Updating produce entries
                for entry in produce:
                    if quantity_left > 0:
                        if entry.sold >= quantity_left:
                            entry.sold = entry.sold - quantity_left
                            entry.save()
                            break
                        else:
                            quantity_left = quantity_left - entry.sold
                            entry.sold = 0
                            entry.save()
                if request.session.get('page', False):
                    return HttpResponseRedirect(request.session['page'])
                else:
                    return HttpResponseRedirect(request.session['page'])
        else:
            return HttpResponseRedirect('/')
    except Exception as e:
        print(e)
        if request.session.get('page', False):
            return HttpResponseRedirect(request.session['page'])
        else:
            return HttpResponseRedirect('/')


# The view for producer to reject a order.
def producer_order_reject(request, cart_id, buyer, crop_id):
    try:
        # if user is authenticated and producer
        if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
            # Queries to obtain buyer, cart and crop
            buyer = User.objects.get(pk=buyer)
            cart = Cart.objects.get(cart_id=cart_id)
            crop = Crop.objects.get(crop_id=crop_id)
            # Query to obtain order to be rejected
            order = Order.objects.get(seller=request.user, cart_id=cart, crop_id=crop, user_id=buyer)
            order.status = "rejected"
            producer_message = order.seller.first_name + " has rejected your order for " + str(order.weight) + " grams of " \
                               + order.crop_id.english_name + " placed on " + str(order.time.date())

            # Creating alert for rejection of order
            Alert.objects.create(user_id=buyer,type="cancelled" ,message=producer_message)
            # Updating crop availability
            crop.availability = crop.availability + order.weight
            # Updating inventory
            inventory = Inventory.objects.get(user_id=request.user, crop_id=crop)
            inventory.sold = inventory.sold - order.weight

            # Creating transaction to save changes
            with transaction.atomic():
                order.save()
                inventory.save()
                crop.save()

                # Query to obtain machines owned by producer
                machines = Machine.objects.filter(user_id=request.user)
                # Query to obtain produce
                produce = Produce.objects.filter(machine_id__in=machines,
                                                 crop_id=crop,
                                                 date_of_expiry__gt=datetime.datetime.now(),
                                                 ).exclude(sold=0).order_by('-date_of_expiry')

                quantity_left = order.weight
                # Updating produce entries
                for entry in produce:
                    if quantity_left > 0:
                        if entry.sold >= quantity_left:
                            entry.sold = entry.sold - quantity_left
                            entry.save()
                            break
                        else:
                            quantity_left = quantity_left - entry.sold
                            entry.sold = 0
                            entry.save()
            if request.session.get('page', False):
                return HttpResponseRedirect(request.session['page'])
            else:
                return HttpResponseRedirect('/')
        else:
            return HttpResponseRedirect('/')
    except Exception as e:
        print(e)
        if request.session.get('page', False):
            return HttpResponseRedirect(request.session['page'])
        else:
            return HttpResponseRedirect('/')


# The view for producer to deliver a order
def producer_order_deliver(request, cart_id, buyer):
    try:
        # if user is authenticated and producer
        if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
            # Queries to obtain buyer, cart
            buyer = User.objects.get(pk=buyer)
            cart = Cart.objects.get(cart_id=cart_id)
            # Query to obtain order to be delivered
            orders = Order.objects.filter(seller=request.user, cart_id=cart, user_id=buyer, status__iexact="pending")

            for order in orders:
                order.status = "delivered"
                order.delivery_date = datetime.datetime.now()
                producer_message = order.seller.first_name + " has delivered your order for " + str(
                    order.weight) + " grams of " \
                                   + order.crop_id.english_name + " placed on " + str(order.time.date())
                # Creating alert for order delivery
                Alert.objects.create(user_id=buyer, type = 'delivered',message=producer_message)
                # Creating transaction
                with transaction.atomic():
                    order.save()

            return HttpResponseRedirect('/producer/deliveredorders/')
        else:
            return HttpResponseRedirect('/')
    except Exception as e:
        print(e)
        if request.session.get('page', False):
            return HttpResponseRedirect(request.session['page'])
        else:
            return HttpResponseRedirect('/')


# The view for the alerts page
def alerts(request):
    try:
        if request.user.is_authenticated:
            # Get last 40 requests
            all_alerts = Alert.objects.filter(user_id=request.user).order_by('-timestamp')[:40]
            paginator = Paginator(all_alerts, 8)  # Show 8 orders per page

            page = request.GET.get('page')
            try:
                alerts = paginator.page(page)
            except PageNotAnInteger:
                # If page is not an integer, deliver first page.
                alerts = paginator.page(1)
            except EmptyPage:
                # If page is out of range (e.g. 9999), deliver last page of results.
                alerts = paginator.page(paginator.num_pages)

            pagelist = []
            for i in range(1, alerts.paginator.num_pages + 1):
                pagelist.append(i)
            if request.user.user_type.upper() == "PRODUCER":
                return render(request, 'login/produceralert.html', {'alerts': alerts , 'pagelist':pagelist})
            else:
                return render(request, 'login/consumeralert.html', {'alerts': alerts , 'pagelist':pagelist})
        else:
            return HttpResponseRedirect('/')
    except Exception as e:
        print(e)
        return HttpResponseRedirect('/')


# Function to convert a given set of dict to a list.
def set_to_list(set_of_dict):
    keys = set_of_dict[0].keys()
    list = []
    list.append(tuple(keys))
    for dict in set_of_dict:
        list.append(tuple(dict.values()))
    return list


# The view for the analytics page.
def analytics(request):
    context = {}
    if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
        inventory = Inventory.objects.filter(user_id=request.user)
        producer_crops = []
        crop_list = []
        for item in inventory:
            producer_crops.append(Crop.objects.get(crop_id=item.crop_id.pk))
        for crop in producer_crops:
            crop_list.append([str(crop.crop_id), crop.english_name])
        print(crop_list)
        form = AnalyticsForm(crop_list=crop_list)
        if request.method == "POST":
            form = AnalyticsForm(request.POST, crop_list=crop_list)
            print(request.POST)
            if form.is_valid():
                print("Printing Data:" + str(form.cleaned_data))
                selected_crops = Crop.objects.filter(pk__in=form.cleaned_data['crops'])
                selected_crops_name = []
                data = []
                for crop in selected_crops:
                    try:
                        machines = Machine.objects.filter(user_id=request.user)
                        start_date = form.cleaned_data['start_date']
                        end_date = form.cleaned_data['end_date']
                        if not start_date:
                            start_date = datetime.date(1, 1, 1)
                        if not end_date:
                            end_date = datetime.date.today()
                        print(start_date, end_date)
                        object = Produce.objects.filter(machine_id__in=machines, crop_id=crop) \
                            .exclude(date_of_produce__date__lt=start_date) \
                            .exclude(date_of_produce__date__gt=end_date)
                        sum_weight = object.aggregate(Sum('weight'))
                        sum_sold = object.aggregate(Sum('sold'))
                        print("SOLD", sum_sold)
                        if sum_weight['weight__sum']:
                            weight = sum_weight['weight__sum']
                        else:
                            weight = 0
                        if sum_sold['sold__sum']:
                            sold = sum_sold['sold__sum']
                        else:
                            sold = 0
                        data.append([crop.short_name, weight, sold])
                        selected_crops_name.append(crop.english_name)
                    except Exception as e:
                        print(e)
                        data.append([crop.short_name, 0])
                        selected_crops_name.append(crop.english_name)
                sorted_data = list(sorted(data, key=lambda data: data[1], reverse=True))
                sorted_data.insert(0, ['Crop Name', 'Weight (g)', 'Sold (g)'])
                data = SimpleDataSource(sorted_data)
                print(sorted_data)
                chart = BarChart(data, html_id='graph', options={'formatter': 'function(y){return y+" gm"}'})
                context['chart'] = chart
                context['data'] = form.cleaned_data
                context['crop_names'] = selected_crops_name

                # Write to a CSV file
                file_name = "media/" + str(request.user.pk) + "_output.csv"
                context['csv_filename'] = file_name
                with open(settings.MEDIA_ROOT + file_name, "w") as f:
                    writer = csv.writer(f)
                    writer.writerows(sorted_data)
            else:
                print("Not Valid")
        context['analyticsform'] = form
        context['page'] = "analytics"
        return render(request, 'analytics.html', context)
    return HttpResponseRedirect("/")

# The view for crop analytics page
def crop_analytics(request):
    context = {}
    if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
        inventory = Inventory.objects.filter(user_id=request.user)
        producer_crops = []
        crop_list = []
        for item in inventory:
            producer_crops.append(Crop.objects.get(crop_id=item.crop_id.pk))
        for crop in producer_crops:
            crop_list.append([str(crop.crop_id), crop.english_name])
        print(crop_list)
        form = CropAnalyticsForm(crop_list=crop_list)
        if request.method == "POST":
            form = CropAnalyticsForm(request.POST, crop_list=crop_list)
            print(request.POST)
            if form.is_valid():
                print("Printing Data:" + str(form.cleaned_data))
                context['data'] = form.cleaned_data
                try:
                    machines = Machine.objects.filter(user_id=request.user)
                    object = Produce.objects.filter(machine_id__in=machines, crop_id=form.cleaned_data['crops'])
                    start_date = form.cleaned_data['start_date']
                    end_date = form.cleaned_data['end_date']
                    if not start_date:
                        start_date = datetime.date(datetime.date.today().year, 1, 1)
                    if not end_date:
                        end_date = datetime.date.today()
                    time_frame = form.cleaned_data['time_frame']
                    data = []
                    context['crop'] = Crop.objects.get(crop_id=form.cleaned_data['crops'])

                    if time_frame == "weekly":
                        first_date = start_date
                        second_date = start_date + datetime.timedelta(weeks=1)
                        while first_date <= end_date:
                            temp = object.exclude(date_of_produce__date__lt=first_date) \
                                .exclude(date_of_produce__date__gte=second_date)
                            print(temp)
                            sum_weight = temp.aggregate(Sum('weight'))
                            sum_sold = temp.aggregate(Sum('sold'))
                            if sum_weight['weight__sum']:
                                weight = sum_weight['weight__sum']
                            else:
                                weight = 0
                            if sum_sold['sold__sum']:
                                sold = sum_sold['sold__sum']
                            else:
                                sold = 0
                            data.append([first_date.strftime('%e %b\'%y'), weight, sold])
                            first_date = first_date + datetime.timedelta(weeks=1)
                            second_date = second_date + datetime.timedelta(weeks=1)
                        data.insert(0, ['Date', 'Weight (g)', 'Sold(g)'])
                        context['table'] = data[1:]
                        data = SimpleDataSource(data)
                        print(data)
                        chart = BarChart(data, html_id='graph', options={'formatter': 'function(y){return y+" gm"}'})
                        context['chart'] = chart
                    elif time_frame == "monthly":
                        cur_month = start_date.month
                        cur_year = start_date.year
                        while datetime.date(cur_year, cur_month, 1) < end_date:
                            if cur_month == 12:
                                temp = object.exclude(date_of_produce__date__lt=datetime.date(cur_year, cur_month, 1)) \
                                    .exclude(date_of_produce__date__gte=datetime.date(cur_year + 1, 1, 1))
                            else:
                                temp = object.exclude(date_of_produce__date__lt=datetime.date(cur_year, cur_month, 1)) \
                                    .exclude(date_of_produce__date__gte=datetime.date(cur_year, cur_month + 1, 1))
                            print(temp)
                            sum_weight = temp.aggregate(Sum('weight'))
                            sum_sold = temp.aggregate(Sum('sold'))
                            if sum_weight['weight__sum']:
                                weight = sum_weight['weight__sum']
                            else:
                                weight = 0
                            if sum_sold['sold__sum']:
                                sold = sum_sold['sold__sum']
                            else:
                                sold = 0
                            data.append([datetime.date(cur_year, cur_month, 1).strftime("%b %Y"), weight, sold])
                            if cur_month == 12:
                                cur_year += 1
                                cur_month = 1
                            else:
                                cur_month += 1
                        data.insert(0, ['Date', 'Weight (g)', 'Sold(g)'])
                        context['table'] = data[1:]
                        data = SimpleDataSource(data)
                        print(data)
                        chart = BarChart(data, html_id='graph', options={'formatter': 'function(y){return y+" gm"}'})
                        context['chart'] = chart
                    elif time_frame == "quaterly":
                        cur_month = start_date.month
                        cur_year = start_date.year
                        while datetime.date(cur_year, cur_month, 1) < end_date:
                            if cur_month == 10:
                                temp = object.exclude(date_of_produce__date__lt=datetime.date(cur_year, cur_month, 1)) \
                                    .exclude(date_of_produce__date__gte=datetime.date(cur_year + 1, 1, 1))
                            else:
                                temp = object.exclude(date_of_produce__date__lt=datetime.date(cur_year, cur_month, 1)) \
                                    .exclude(date_of_produce__date__gte=datetime.date(cur_year, cur_month + 3, 1))
                            print(temp)
                            sum_weight = temp.aggregate(Sum('weight'))
                            sum_sold = temp.aggregate(Sum('sold'))
                            if sum_weight['weight__sum']:
                                weight = sum_weight['weight__sum']
                            else:
                                weight = 0
                            if sum_sold['sold__sum']:
                                sold = sum_sold['sold__sum']
                            else:
                                sold = 0
                            data.append([datetime.date(cur_year, cur_month, 1).strftime("%B %Y"), weight, sold])
                            if cur_month == 10:
                                cur_year += 1
                                cur_month = 1
                            else:
                                cur_month += 3
                        data.insert(0, ['Date', 'Weight (g)', 'Sold(g)'])
                        context['table'] = data[1:]
                        data = SimpleDataSource(data)
                        print(data)
                        chart = BarChart(data, html_id='graph', options={'formatter': 'function(y){return y+" gm"}'})
                        context['chart'] = chart

                except Exception as e:
                    print(e)
        context['analyticsform'] = form
        context['page'] = "analytics"
        return render(request, 'crop_analytics.html', context)
    return HttpResponseRedirect("/")


# The view to allow editing of inventory to producer.
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def edit_inventory(request, crop_id):
    context = {}
    if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
        try:
            crop = Crop.objects.get(pk=crop_id)
            inventory = Inventory.objects.get(crop_id=crop, user_id=request.user)
            form = InventoryForm(instance=inventory)
            print("Form\n")
            if request.method == "POST":
                form = InventoryForm(request.POST)
                if form.is_valid():
                    print("DATA\n", form.cleaned_data)
                    o = InventoryForm(request.POST, instance=inventory)
                    o.save()
                    messages.success(request, "Your Inventory was Successfully Updated!", fail_silently=True)
            context['inventory'] = inventory
            context['form'] = form
            context['page'] = "edit_inventory"
            return render(request, "edit_inventory.html", context)
        except Exception as e:
            print(e)
            return HttpResponseRedirect(request.session.get("page","/"))
    return HttpResponseRedirect("/")


# The view to allow editing of inventory to producer.
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def edit_produce(request, produce_pk):
    context = {}
    if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
        try:
            remove_expired_produce()
            machines = Machine.objects.filter(user_id=request.user)
            produce = Produce.objects.get(pk=produce_pk, machine_id__in=machines)
            form = ProduceForm(instance=produce)
            previous_wasted = produce.wasted
            print("Form\n")
            if request.method == "POST":
                form = ProduceForm(request.POST)
                if form.is_valid():
                    print("DATA\n", form.cleaned_data)
                    o = ProduceForm(request.POST, instance=produce)
                    o = o.save()
                    inventory = Inventory.objects.get(user_id=request.user, crop_id=produce.crop_id)
                    crop = Crop.objects.get(crop_id = produce.crop_id.crop_id)
                    inventory.wasted = inventory.wasted - previous_wasted + o.wasted
                    crop.availability = crop.availability + previous_wasted - o.wasted
                    with transaction.atomic():
                        inventory.save()
                        crop.save()
                    remove_expired_produce()
                    messages.success(request, "Your Produce was Successfully Updated!", fail_silently=True)
            context['produce'] = produce
            context['form'] = form
            context['page'] = "edit_produce"
            return render(request, "edit_produce.html", context)
        except Exception as e:
            print(e)
            return HttpResponseRedirect(request.session.get("page","/"))
    return HttpResponseRedirect("/")

# The view for download of csv for overall analytics by producer.
def download(request):
    if request.user.is_authenticated:
        file_name = "media/" + str(request.user.pk) + "_output.csv"
        file_path = os.path.join(settings.MEDIA_ROOT, file_name)
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                response = HttpResponse(f.read(), content_type="text/csv")
                response['Content-Disposition'] = 'attachment; filename=' + "report.csv"
                return response
    return HttpResponseRedirect(request.session.get('page', "/"))

# The view for profile page of producer
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def producer_profile(request):
    if request.user.is_authenticated and request.user.user_type.upper() == "PRODUCER":
        context = {}
        form = UserForm(instance = request.user)
        print("Form\n")
        if request.method == "POST":
            form = UserForm(request.POST)
            if form.is_valid():
                print("DATA\n", form.cleaned_data)
                o = UserForm(request.POST, instance=request.user)
                o.save()
                try:
                    Alert.objects.get(user_id=request.user, type="start_message").delete()
                except:
                    pass
        context['form'] = form
        context['page'] = "producer_profile"
        return render(request, "producer_profile.html", context)
    return  HttpResponseRedirect(request.session.get('page',"/"))

# The view for profile page of consumer
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def consumer_profile(request):
    if request.user.is_authenticated and request.user.user_type.upper() == "CONSUMER":
        context = {}
        form = UserForm(instance = request.user)
        print("Form\n")
        if request.method == "POST":
            form = UserForm(request.POST)
            if form.is_valid():
                print("DATA\n", form.cleaned_data)
                o = UserForm(request.POST, instance=request.user)
                o.save()
                try:
                    Alert.objects.get(user_id=request.user, type="start_message").delete()
                except:
                    pass
        context['form'] = form
        context['page'] = "consumer_profile"
        return render(request, "consumer_profile.html", context)
    return  HttpResponseRedirect(request.session.get('page',"/"))

# The view to change password of user account
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def change_password(request):
    if request.user.is_authenticated:
        context = {}
        if request.method == 'POST':
            form = PasswordChangeForm(request.user, request.POST)
            if form.is_valid():
                user = form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Your Password was Successfully Updated!", fail_silently=True)
                return HttpResponseRedirect(request.session.get('page',"/"))
            print(form)
        else:
            form = PasswordChangeForm(request.user)
        context['form'] = form
        if request.user.user_type.upper() == "PRODUCER":
            return render(request, 'change_password.html', context)
        return render(request,'consumer_change_password.html', context)
